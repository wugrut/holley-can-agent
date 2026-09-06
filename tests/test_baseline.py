"""
Unit tests for vehicle baseline engine, multidimensional bins, and non-parametric metrics.
"""

import pytest

from app.baseline.bins import LoadBand, OperatingCondition, RPMBand, ThermalBand
from app.baseline.engine import BaselineEngine
from app.baseline.model import RobustStats
from app.telemetry.sample import NormalizedTelemetrySample


class TestBaselineBinningAndClassification:
    def test_idle_bin_classification(self):
        cond = OperatingCondition.classify(rpm=850.0, map_kpa=35.0, coolant_temp=185.0)
        assert cond.rpm_band == RPMBand.IDLE
        assert cond.load_band == LoadBand.LIGHT
        assert cond.thermal_band == ThermalBand.OPERATING
        assert cond.key == "idle_light_operating"

    def test_cruise_bin_classification(self):
        cond = OperatingCondition.classify(rpm=2400.0, map_kpa=48.0, coolant_temp=190.0)
        assert cond.rpm_band == RPMBand.CRUISE
        assert cond.load_band == LoadBand.LIGHT
        assert cond.thermal_band == ThermalBand.OPERATING
        assert cond.key == "cruise_light_operating"

    def test_boost_bin_classification(self):
        cond = OperatingCondition.classify(rpm=5800.0, map_kpa=180.0, coolant_temp=200.0)
        assert cond.rpm_band == RPMBand.HIGH
        assert cond.load_band == LoadBand.BOOST
        assert cond.thermal_band == ThermalBand.OPERATING
        assert cond.key == "high_boost_operating"

    def test_cold_idle_classification(self):
        cond = OperatingCondition.classify(rpm=950.0, map_kpa=45.0, coolant_temp=120.0)
        assert cond.thermal_band == ThermalBand.COLD
        assert cond.key == "idle_light_cold"


class TestRobustStatistics:
    def test_robust_stats_computation(self):
        # 20 samples with known distribution around 0.0 with one outlier
        data = [0.1, -0.2, 0.0, 0.3, -0.1, 0.2, -0.3, 0.1, 0.0, -0.1,
                0.2, -0.2, 0.1, -0.1, 0.0, 0.2, -0.2, 0.1, 0.0, 10.0]  # outlier: 10.0
        stats = RobustStats.compute(data)
        assert stats is not None
        assert stats.count == 20
        # Median is robust against the 10.0 outlier
        assert stats.median == pytest.approx(0.05, abs=0.1)
        assert stats.iqr < 1.0
        assert stats.max_val == 10.0


class TestBaselineEngine:
    def test_engine_ingests_and_learns_baseline(self):
        engine = BaselineEngine(vehicle_id="veh_test_ls3")

        # Ingest 30 normal idle samples
        for i in range(30):
            s = NormalizedTelemetrySample(
                timestamp=1000.0 + i,
                engine_rpm=850.0 + (i % 3),
                map_kpa=36.0,
                coolant_temp=185.0,
                fuel_learn=1.0 + ((i % 5) * 0.1),
                target_afr=14.7,
                afr_measured=14.7,
            )
            engine.ingest_sample(s)

        cond_key = "idle_light_operating"
        cell = engine.profile.cells.get(f"{cond_key}:fuel_learn")
        assert cell is not None
        assert cell.stats.count >= 20
        assert cell.stats.median == pytest.approx(1.2, abs=0.2)

        # Evaluate normal value
        eval_normal = engine.evaluate_deviation(cond_key, "fuel_learn", 1.2)
        assert eval_normal is not None
        assert abs(eval_normal["delta"]) < 0.3
        assert eval_normal["is_outside_p05_p95"] == 0.0

        # Evaluate significant deviation (+8.5%)
        eval_abnormal = engine.evaluate_deviation(cond_key, "fuel_learn", 8.5)
        assert eval_abnormal is not None
        assert eval_abnormal["delta"] > 7.0
        assert eval_abnormal["is_outside_p05_p95"] == 1.0
