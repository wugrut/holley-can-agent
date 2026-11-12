"""
Automated unit tests for the rule-based DiagnosticEngine and evidence chaining.
"""

import json
from pathlib import Path
import pytest

from app.diagnostics.engine import DiagnosticEngine
from app.events.detector import EventDetector
from app.telemetry.sample import NormalizedTelemetrySample


def load_fixture_samples(fixture_name: str) -> list[NormalizedTelemetrySample]:
    """Helper loading samples from data/fixtures/."""
    path = Path(__file__).parent.parent / "data" / "fixtures" / fixture_name
    with open(path, "r") as f:
        data = json.load(f)

    samples = []
    for item in data["samples"]:
        s = NormalizedTelemetrySample(
            timestamp=item["t"],
            engine_rpm=item["rpm"],
            map_kpa=item["map_kpa"],
            tps=item["tps"],
            coolant_temp=item["clt"],
            target_afr=item["target_afr"],
            afr_measured=item["afr"],
            fuel_learn=item["fuel_learn"],
            battery_voltage=item["voltage"],
        )
        s.compute_derived_metrics()
        samples.append(s)
    return samples


class TestDiagnosticEngine:
    def test_high_load_fueling_deviation_diagnostic(self):
        engine = DiagnosticEngine()
        detector = EventDetector()
        samples = load_fixture_samples("lean_high_load.json")

        events = []
        for s in samples:
            events.extend(detector.feed_sample(s))

        diagnostics = engine.evaluate_session(samples, events)
        assert len(diagnostics) >= 1

        fuel_diag = next((d for d in diagnostics if d.diagnostic_id == "DIAG_FUEL_HIGH_LOAD_DEV"), None)
        assert fuel_diag is not None
        assert fuel_diag.severity in ("warning", "critical")
        assert fuel_diag.confidence >= 0.8
        assert "Closed-loop fuel learn averaged" in fuel_diag.observation
        assert len(fuel_diag.evidence) >= 3
        assert len(fuel_diag.possible_causes) >= 2
        assert len(fuel_diag.recommended_tests) >= 2
        assert any("fuel rail pressure" in t.lower() for t in fuel_diag.recommended_tests)

    def test_idle_hunting_diagnostic(self):
        engine = DiagnosticEngine()
        detector = EventDetector()
        samples = load_fixture_samples("unstable_idle.json")

        events = []
        for s in samples:
            events.extend(detector.feed_sample(s))

        diagnostics = engine.evaluate_session(samples, events)
        idle_diag = next((d for d in diagnostics if d.diagnostic_id == "DIAG_IDLE_RPM_HUNTING"), None)
        assert idle_diag is not None
        assert idle_diag.category == "idle"
        assert idle_diag.confidence >= 0.9
        assert any("ignition timing" in c.lower() for c in idle_diag.possible_causes)

    def test_sensor_implausibility_diagnostic(self):
        engine = DiagnosticEngine()
        samples = load_fixture_samples("sensor_dropout.json")

        diagnostics = engine.evaluate_session(samples, events=[])
        map_diag = next((d for d in diagnostics if d.diagnostic_id == "DIAG_SENSOR_IMPLAUSIBLE_MAP_TPS"), None)
        assert map_diag is not None
        assert map_diag.category == "sensors"
        assert any("vacuum" in c.lower() for c in map_diag.possible_causes)

    def test_low_voltage_diagnostic(self):
        engine = DiagnosticEngine()
        samples = load_fixture_samples("low_voltage.json")

        diagnostics = engine.evaluate_session(samples, events=[])
        volt_diag = next((d for d in diagnostics if d.diagnostic_id == "DIAG_ELEC_LOW_VOLTAGE"), None)
        assert volt_diag is not None
        assert volt_diag.category == "electrical"
        assert volt_diag.severity == "critical"  # Min voltage 11.2V triggers critical (<11.5V)

    def test_coolant_overheat_diagnostic(self):
        engine = DiagnosticEngine()
        samples = load_fixture_samples("thermal_event.json")

        diagnostics = engine.evaluate_session(samples, events=[])
        clt_diag = next((d for d in diagnostics if d.diagnostic_id == "DIAG_THERMAL_COOLANT_OVERHEAT"), None)
        assert clt_diag is not None
        assert clt_diag.category == "thermal"
        assert clt_diag.severity == "critical"  # > 235 °F triggers critical

    def test_rich_cruise_diagnostic(self):
        engine = DiagnosticEngine()
        samples = load_fixture_samples("rich_cruise.json")

        diagnostics = engine.evaluate_session(samples, events=[])
        rich_diag = next((d for d in diagnostics if d.diagnostic_id == "DIAG_FUEL_RICH_DRIFT"), None)
        assert rich_diag is not None
        assert rich_diag.category == "fueling"

    def test_healthy_runs_produce_no_false_alerts(self):
        engine = DiagnosticEngine()
        detector = EventDetector()

        # Normal idle: should have zero warnings
        idle_samples = load_fixture_samples("normal_idle.json")
        idle_events = []
        for s in idle_samples:
            idle_events.extend(detector.feed_sample(s))
        idle_diags = engine.evaluate_session(idle_samples, idle_events)
        assert len(idle_diags) == 0, f"Expected 0 diagnostics on normal idle, got {len(idle_diags)}"

        # Normal WOT: should have zero warnings
        wot_samples = load_fixture_samples("normal_wot.json")
        wot_events = []
        for s in wot_samples:
            wot_events.extend(detector.feed_sample(s))
        wot_diags = engine.evaluate_session(wot_samples, wot_events)
        assert len(wot_diags) == 0, f"Expected 0 diagnostics on healthy WOT pull, got {len(wot_diags)}"

    @pytest.mark.anyio
    async def test_alerts_sensor_circuit_fault_detection(self):
        from holley_can.alerts import AlertEngine
        from holley_can.protocol import DecodedFrame, CHANNEL_BY_NAME

        engine = AlertEngine()
        ch_clt = CHANNEL_BY_NAME["coolant_temp"]

        # 1. Frame with fault flag (0x02: Above Max / Open Circuit)
        fault_frame = DecodedFrame(
            timestamp=100.0,
            channel_index=ch_clt.index,
            channel_def=ch_clt,
            value_a=260.0,
            value_b=2.0,  # 0x02 = Open circuit / Short to 5V
            raw_id=0x1E007800,
            raw_data=b"\x00" * 8,
            ecu_serial_bits=0x1A5,
            protocol="hefi",
        )
        await engine.on_frame(fault_frame)
        active = engine.get_active_alerts()
        circuit_alerts = [a for a in active if "circuit_fault" in a["alert_type"]]
        assert len(circuit_alerts) == 1
        assert "Open Circuit / Short to 5V" in circuit_alerts[0]["message"]
        assert circuit_alerts[0]["severity"] == "critical"

        # 2. Healthy frame clears the fault
        healthy_frame = DecodedFrame(
            timestamp=101.0,
            channel_index=ch_clt.index,
            channel_def=ch_clt,
            value_a=185.0,
            value_b=0.0,  # 0x00 = Healthy
            raw_id=0x1E007800,
            raw_data=b"\x00" * 8,
            ecu_serial_bits=0x1A5,
            protocol="hefi",
        )
        await engine.on_frame(healthy_frame)
        active_after = engine.get_active_alerts()
        circuit_alerts_after = [a for a in active_after if "circuit_fault" in a["alert_type"]]
        assert len(circuit_alerts_after) == 0
