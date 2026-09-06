"""
Unit tests verifying all deterministic simulation scenarios.
"""

import pytest

from app.hardware.simulator import SimulationScenario, VirtualSimulatorAdapter
from app.protocol.hefi import extract_channel_index, extract_ecu_serial


class TestSimulatorScenarios:
    def test_idle_stable_scenario(self):
        adapter = VirtualSimulatorAdapter(scenario=SimulationScenario.IDLE_STABLE, ecu_serial=0x1A5)
        frames = adapter.step_deterministic(dt=0.1)

        assert len(frames) >= 15
        rpm_frame = next(f for f in frames if extract_channel_index(f.arbitration_id) == 1)
        assert rpm_frame is not None
        assert extract_ecu_serial(rpm_frame.arbitration_id) == 0x1A5
        assert 800.0 <= adapter.rpm <= 900.0
        assert adapter.tps == 0.0
        assert 30.0 <= adapter.map_kpa <= 40.0

    def test_idle_unstable_scenario(self):
        adapter = VirtualSimulatorAdapter(scenario=SimulationScenario.IDLE_UNSTABLE)
        # Advance through multiple time steps to observe hunting oscillation
        rpms = []
        for _ in range(30):
            adapter.step_deterministic(dt=0.1)
            rpms.append(adapter.rpm)

        max_rpm = max(rpms)
        min_rpm = min(rpms)
        amplitude = max_rpm - min_rpm
        assert amplitude > 200.0, f"Expected hunting amplitude > 200 RPM, got {amplitude}"

    def test_cruise_rich_drift_scenario(self):
        adapter = VirtualSimulatorAdapter(scenario=SimulationScenario.CRUISE_RICH_DRIFT)
        # Run for 20 seconds simulated time
        for _ in range(200):
            adapter.step_deterministic(dt=0.1)

        assert adapter.fuel_learn <= -5.0
        assert adapter.vehicle_speed == 0.0 or adapter.trans_gear == 4

    def test_wot_pull_lean_dev_scenario(self):
        adapter = VirtualSimulatorAdapter(scenario=SimulationScenario.WOT_PULL_LEAN_DEV)
        # Advance into the WOT phase (t = 2.5s)
        for _ in range(25):
            adapter.step_deterministic(dt=0.1)

        assert adapter.tps == 100.0
        assert adapter.rpm > 3500.0
        assert adapter.fuel_learn > 7.0, f"Expected lean deviation > 7%, got {adapter.fuel_learn}"

    def test_thermal_event_scenario(self):
        adapter = VirtualSimulatorAdapter(scenario=SimulationScenario.THERMAL_EVENT)
        initial_clt = adapter.coolant_temp
        for _ in range(200):
            adapter.step_deterministic(dt=0.1)

        assert adapter.coolant_temp > initial_clt
        assert adapter.coolant_temp >= 225.0

    def test_low_voltage_scenario(self):
        adapter = VirtualSimulatorAdapter(scenario=SimulationScenario.LOW_VOLTAGE)
        for _ in range(100):
            adapter.step_deterministic(dt=0.1)

        assert adapter.battery_voltage < 12.0

    def test_sensor_dropout_scenario(self):
        adapter = VirtualSimulatorAdapter(scenario=SimulationScenario.SENSOR_DROPOUT)
        # Before 2 seconds: valid
        adapter.step_deterministic(dt=1.0)
        assert adapter.tps == 25.0
        assert adapter.map_kpa == 52.0

        # After 2 seconds: dropout
        for _ in range(20):
            adapter.step_deterministic(dt=0.1)

        assert adapter.tps == 0.0
        assert adapter.map_kpa == 0.0
