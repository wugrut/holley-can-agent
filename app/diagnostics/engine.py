"""
Rule-based diagnostic engine executing high-confidence deterministic evaluations.
"""

from __future__ import annotations

from typing import List, Optional
import numpy as np

from app.baseline.engine import BaselineEngine
from app.diagnostics.finding import DiagnosticEvidenceItem, StructuredDiagnostic
from app.events.types import EngineEvent, EventType
from app.telemetry.sample import NormalizedTelemetrySample


from app.vehicle.profile import VehicleProfile


class DiagnosticEngine:
    """
    Evaluates session telemetry, detected events, and baseline profiles against
    deterministic automotive diagnostic rules.
    """

    def __init__(
        self,
        baseline_engine: Optional[BaselineEngine] = None,
        vehicle_profile: Optional[VehicleProfile] = None,
    ) -> None:
        self.baseline_engine = baseline_engine
        self.profile = vehicle_profile or VehicleProfile()

    def evaluate_session(
        self,
        samples: List[NormalizedTelemetrySample],
        events: List[EngineEvent],
    ) -> List[StructuredDiagnostic]:
        """Runs the suite of diagnostic rules across session telemetry and events."""
        if not samples:
            return []

        diagnostics: List[StructuredDiagnostic] = []

        valid_count = sum(1 for s in samples if s.overall_quality_score >= 0.8)
        valid_pct = round((valid_count / len(samples)) * 100.0, 1)

        # 1. High-Load Fueling Deviation Rule
        diag_fuel_wot = self._eval_high_load_fueling(samples, events, valid_pct)
        if diag_fuel_wot:
            diagnostics.append(diag_fuel_wot)

        # 2. Idle RPM Hunting Rule
        diag_idle = self._eval_idle_hunting(events, valid_pct)
        if diag_idle:
            diagnostics.append(diag_idle)

        # 3. Sensor Implausibility (High MAP at Closed Throttle & High RPM)
        diag_map_tps = self._eval_implausible_map_tps(samples, valid_pct)
        if diag_map_tps:
            diagnostics.append(diag_map_tps)

        # 4. Low Voltage / Charging System
        diag_volt = self._eval_low_voltage(samples, events, valid_pct)
        if diag_volt:
            diagnostics.append(diag_volt)

        # 5. Coolant Overheating Rule
        diag_therm = self._eval_coolant_overheat(samples, events, valid_pct)
        if diag_therm:
            diagnostics.append(diag_therm)

        # 6. Persistent Rich Cruise Drift Rule
        diag_rich = self._eval_rich_cruise(samples, valid_pct)
        if diag_rich:
            diagnostics.append(diag_rich)

        return diagnostics

    def _eval_high_load_fueling(
        self,
        samples: List[NormalizedTelemetrySample],
        events: List[EngineEvent],
        valid_pct: float,
    ) -> Optional[StructuredDiagnostic]:
        """Checks for sustained positive fuel correction during WOT acceleration."""
        wot_events = [e for e in events if e.event_type == EventType.WOT_PULL]
        high_load_samples = [
            s for s in samples
            if s.tps >= 85.0 and s.map_kpa >= 85.0 and s.engine_rpm >= 3500.0
        ]

        if not high_load_samples:
            return None

        learn_values = [s.fuel_learn for s in high_load_samples]
        mean_correction = float(np.mean(learn_values))

        threshold = self.profile.fuel_learn_threshold_pct
        if mean_correction >= threshold:
            rpm_min = min(s.engine_rpm for s in high_load_samples)
            rpm_max = max(s.engine_rpm for s in high_load_samples)
            map_min = min(s.map_kpa for s in high_load_samples)
            map_max = max(s.map_kpa for s in high_load_samples)
            base_fp = self.profile.base_fuel_pressure_psi

            evidence = [
                DiagnosticEvidenceItem("rpm_range", f"{rpm_min:.0f} - {rpm_max:.0f}", "rpm", description="Observed high-load engine speed band"),
                DiagnosticEvidenceItem("map_range", f"{map_min:.1f} - {map_max:.1f}", "kPa", description="Observed high-load manifold pressure"),
                DiagnosticEvidenceItem("mean_fuel_learn", f"{mean_correction:+.1f}", "%", description="ECU closed-loop learn correction (ECU-provided)"),
                DiagnosticEvidenceItem("drift_threshold", f"+{threshold:.1f}%", "%", description="Threshold origin: generic heuristic"),
                DiagnosticEvidenceItem("high_load_samples", len(high_load_samples), "samples"),
                DiagnosticEvidenceItem("wot_events_count", len(wot_events), "events"),
            ]

            return StructuredDiagnostic(
                diagnostic_id="DIAG_FUEL_HIGH_LOAD_DEV",
                title="High-Load Fueling Deviation",
                severity="warning" if mean_correction < 12.0 else "critical",
                category="fueling",
                observation=(
                    f"Closed-loop fuel learn averaged {mean_correction:+.1f}% across high-load "
                    f"operation ({rpm_min:.0f}–{rpm_max:.0f} RPM, {map_min:.0f}–{map_max:.0f} kPa)."
                ),
                evidence=evidence,
                inferred_condition=(
                    "The engine consistently requires significant positive fueling correction at high load, "
                    "indicating that cylinder air charge is higher than calibrated in the base VE table, or "
                    "fuel delivery is restricted under peak demand."
                ),
                possible_causes=[
                    "Volumetric Efficiency (VE) table values are low in the high-load / high-RPM cells",
                    "Fuel rail pressure drop during sustained high injector duty cycle",
                    "Exhaust manifold or collector leak upstream of wideband O2 sensor introducing unmetered oxygen",
                ],
                recommended_tests=[
                    f"Verify mechanical fuel rail pressure with a physical gauge or fuel pressure transducer log during WOT to ensure pressure holds steady at {base_fp:.0f} PSI (vehicle-configured base specification)",
                    "Perform smoke or pressure check on header collector joints and O2 bungs",
                    "If fuel pressure and mechanical integrity are verified, review and apply fuel trims to the base fuel table in Holley software",
                ],
                confidence=0.94 if len(high_load_samples) >= 5 else 0.75,
                data_validity_pct=valid_pct,
            )

        return None

    def _eval_idle_hunting(
        self,
        events: List[EngineEvent],
        valid_pct: float,
    ) -> Optional[StructuredDiagnostic]:
        """Detects idle oscillation and hunting events."""
        hunting_events = [e for e in events if e.event_type == EventType.IDLE_HUNTING]
        if not hunting_events:
            return None

        event = hunting_events[0]
        amp = event.calculated_metrics.get("rpm_amplitude", 200.0)

        evidence = [
            DiagnosticEvidenceItem("rpm_amplitude", f"±{amp:.0f}", "rpm"),
            DiagnosticEvidenceItem("min_rpm", event.calculated_metrics.get("min_rpm", 650), "rpm"),
            DiagnosticEvidenceItem("max_rpm", event.calculated_metrics.get("max_rpm", 1100), "rpm"),
            DiagnosticEvidenceItem("duration_s", event.duration_s, "s"),
        ]

        return StructuredDiagnostic(
            diagnostic_id="DIAG_IDLE_RPM_HUNTING",
            title="Idle RPM Hunting & Oscillation",
            severity="warning",
            category="idle",
            observation=f"Warm idle RPM oscillated with an amplitude of {amp:.0f} RPM.",
            evidence=evidence,
            inferred_condition="Closed-loop idle control or ignition timing is in a positive feedback surge oscillation.",
            possible_causes=[
                "Steep ignition timing slope around idle cells causing timing over-advance when RPM dips",
                "Idle Air Control (IAC) proportional gain too aggressive",
                "Intake manifold vacuum leak causing erratic cylinder filling at low throttle angles",
            ],
            recommended_tests=[
                "Flatten ignition timing to a flat plateau (e.g. 18° BTDC) across idle RPM and MAP cells",
                "Inspect IAC steps / duty cycle in live monitor; adjust mechanical throttle blade stop screw if IAC is near 0% or 100%",
                "Perform smoke test on intake manifold gaskets, PCV hoses, and vacuum ports",
            ],
            confidence=0.95,
            data_validity_pct=valid_pct,
        )

    def _eval_implausible_map_tps(
        self,
        samples: List[NormalizedTelemetrySample],
        valid_pct: float,
    ) -> Optional[StructuredDiagnostic]:
        """Detects high MAP reading while throttle is completely closed at elevated RPM."""
        anomaly_samples = [
            s for s in samples
            if s.engine_rpm >= 2000.0 and s.tps <= 1.0 and s.map_kpa >= 80.0
        ]

        if len(anomaly_samples) >= 3:
            evidence = [
                DiagnosticEvidenceItem("anomaly_samples_count", len(anomaly_samples), "samples"),
                DiagnosticEvidenceItem("peak_map_at_closed_tps", max(s.map_kpa for s in anomaly_samples), "kPa"),
            ]

            return StructuredDiagnostic(
                diagnostic_id="DIAG_SENSOR_IMPLAUSIBLE_MAP_TPS",
                title="Implausible Engine Vacuum vs Throttle Position",
                severity="warning",
                category="sensors",
                observation="Manifold pressure remained above 80 kPa while throttle was closed at >2000 RPM.",
                evidence=evidence,
                inferred_condition="Manifold vacuum was lost or MAP transducer line is disconnected/leaking.",
                possible_causes=[
                    "MAP sensor vacuum reference hose disconnected or split",
                    "Major intake manifold or brake booster vacuum leak",
                    "MAP sensor transducer calibration or wiring fault",
                ],
                recommended_tests=[
                    "Inspect MAP vacuum reference hose between intake plenum and sensor",
                    "Verify key-on engine-off MAP reading matches ambient barometric pressure (~101 kPa at sea level)",
                ],
                confidence=0.92,
                data_validity_pct=valid_pct,
            )

        return None

    def _eval_low_voltage(
        self,
        samples: List[NormalizedTelemetrySample],
        events: List[EngineEvent],
        valid_pct: float,
    ) -> Optional[StructuredDiagnostic]:
        """Detects charging system sag under running load."""
        sag_events = [e for e in events if e.event_type == EventType.VOLTAGE_SAG]
        running_samples = [s for s in samples if s.engine_rpm >= 1000.0]
        if not running_samples:
            return None

        low_volt_samples = [s for s in running_samples if s.battery_voltage < 12.2]
        if len(low_volt_samples) >= 3 or sag_events:
            min_v = min(s.battery_voltage for s in running_samples)
            evidence = [
                DiagnosticEvidenceItem("min_voltage", f"{min_v:.2f}", "V"),
                DiagnosticEvidenceItem("low_voltage_samples", len(low_volt_samples), "samples"),
            ]

            return StructuredDiagnostic(
                diagnostic_id="DIAG_ELEC_LOW_VOLTAGE",
                title="Low System Battery Voltage Under Load",
                severity="warning" if min_v >= 11.5 else "critical",
                category="electrical",
                observation=f"Battery voltage dropped to {min_v:.2f}V while engine was running.",
                evidence=evidence,
                inferred_condition="Charging system output is insufficient to sustain vehicle electrical load.",
                possible_causes=[
                    "Alternator belt slipping under load",
                    "Alternator internal diode or voltage regulator failure",
                    "High resistance in main ground strap or battery feed wiring",
                ],
                recommended_tests=[
                    "Measure voltage directly across battery posts with a calibrated multimeter while engine is idling and headlights/fans are active",
                    "Inspect alternator belt tension and pulley alignment",
                    "Check engine block to chassis and battery negative ground cables for corrosion or loose hardware",
                ],
                confidence=0.95,
                data_validity_pct=valid_pct,
            )

        return None

    def _eval_coolant_overheat(
        self,
        samples: List[NormalizedTelemetrySample],
        events: List[EngineEvent],
        valid_pct: float,
    ) -> Optional[StructuredDiagnostic]:
        """Detects coolant temperatures exceeding safe thresholds."""
        hot_samples = [s for s in samples if s.coolant_temp >= 225.0]
        if not hot_samples:
            return None

        peak_clt = max(s.coolant_temp for s in hot_samples)
        evidence = [
            DiagnosticEvidenceItem("peak_coolant_temp", f"{peak_clt:.1f}", "°F"),
            DiagnosticEvidenceItem("samples_above_225F", len(hot_samples), "samples"),
        ]

        return StructuredDiagnostic(
            diagnostic_id="DIAG_THERMAL_COOLANT_OVERHEAT",
            title="Engine Coolant Temperature Overheating",
            severity="warning" if peak_clt < 235.0 else "critical",
            category="thermal",
            observation=f"Coolant temperature reached {peak_clt:.1f}°F, exceeding the 225°F threshold.",
            evidence=evidence,
            inferred_condition="Cooling system heat rejection is inadequate for current engine thermal dissipation.",
            possible_causes=[
                "Cooling fan inoperative or configured with incorrect activation temperature",
                "Air pocket trapped in cooling passages / cylinder heads",
                "Thermostat sticking closed or restricted radiator flow",
            ],
            recommended_tests=[
                "Verify electric fan triggers and air is drawn through radiator core",
                "Use cooling system vacuum filler or burp funnel to bleed trapped air",
                "Inspect radiator core with infrared thermometer to identify cold spots indicative of internal blockage",
            ],
            confidence=0.98,
            data_validity_pct=valid_pct,
        )

    def _eval_rich_cruise(
        self,
        samples: List[NormalizedTelemetrySample],
        valid_pct: float,
    ) -> Optional[StructuredDiagnostic]:
        """Detects persistent negative fuel learn during highway cruise."""
        cruise_samples = [
            s for s in samples
            if 1800.0 <= s.engine_rpm <= 3000.0 and 35.0 <= s.map_kpa <= 65.0
        ]
        if len(cruise_samples) < 5:
            return None

        mean_learn = float(np.mean([s.fuel_learn for s in cruise_samples]))
        if mean_learn <= -10.0:
            evidence = [
                DiagnosticEvidenceItem("mean_cruise_learn", f"{mean_learn:+.1f}", "%"),
                DiagnosticEvidenceItem("cruise_samples_count", len(cruise_samples), "samples"),
            ]

            return StructuredDiagnostic(
                diagnostic_id="DIAG_FUEL_RICH_DRIFT",
                title="Persistent Rich Fuel Learn Drift in Cruise",
                severity="warning",
                category="fueling",
                observation=f"Closed-loop fuel learn averaged {mean_learn:+.1f}% across cruise cells.",
                evidence=evidence,
                inferred_condition="ECU is removing significant fuel to maintain target air-fuel ratio during steady cruise.",
                possible_causes=[
                    "Base volumetric efficiency (VE) table values too high in 2000-3000 RPM / 40-60 kPa cells",
                    "Fuel rail pressure higher than ECU baseline configuration",
                    "Leaking fuel pressure regulator diaphragm or dripping injector",
                ],
                recommended_tests=[
                    "Check fuel rail pressure at idle and cruise vacuum with mechanical gauge",
                    "Inspect spark plugs to determine if rich condition is across all cylinders or isolated to one",
                    "Review base fuel table in Holley software and apply learned negative trims",
                ],
                confidence=0.91,
                data_validity_pct=valid_pct,
            )

        return None
