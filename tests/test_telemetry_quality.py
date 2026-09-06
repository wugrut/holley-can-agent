"""
Unit tests for telemetry signal validation, quality grading, and normalized calculations.
"""

import math
import time
import pytest

from app.telemetry.quality import SignalQuality
from app.telemetry.sample import NormalizedTelemetrySample
from app.telemetry.signals import TelemetrySignal
from app.telemetry.validator import SignalValidator


class TestSignalValidator:
    def test_valid_signal(self):
        validator = SignalValidator()
        sig = validator.validate(
            signal_name="engine_rpm",
            value=850.0,
            unit="rpm",
            timestamp=time.time(),
            source="can",
            raw_channel_index=1,
        )
        assert sig.quality == SignalQuality.VALID
        assert sig.value == 850.0
        assert sig.confidence == 1.0
        assert sig.is_usable_for_baseline is True

    def test_out_of_range_signal(self):
        validator = SignalValidator()
        sig = validator.validate(
            signal_name="tps",
            value=125.0,  # Exceeds max 105%
            unit="%",
            timestamp=time.time(),
            source="can",
        )
        assert sig.quality == SignalQuality.OUT_OF_RANGE
        assert sig.confidence < 0.5
        assert sig.is_usable_for_baseline is False

    def test_nan_rejected(self):
        validator = SignalValidator()
        sig = validator.validate(
            signal_name="map_kpa",
            value=float("nan"),
            unit="kPa",
            timestamp=time.time(),
        )
        assert sig.quality == SignalQuality.INVALID
        assert sig.confidence == 0.0
        assert sig.is_usable_for_baseline is False

    def test_inf_rejected(self):
        validator = SignalValidator()
        sig = validator.validate(
            signal_name="battery_voltage",
            value=float("inf"),
            unit="V",
            timestamp=time.time(),
        )
        assert sig.quality == SignalQuality.INVALID
        assert sig.is_usable_for_baseline is False

    def test_staleness_detection(self):
        validator = SignalValidator(staleness_timeout_s=0.1)
        now = time.time()
        # First sample: fresh
        sig1 = validator.validate("engine_rpm", 850.0, "rpm", now)
        assert sig1.quality == SignalQuality.VALID

        # Sleep past staleness timeout
        time.sleep(0.15)
        sig2 = validator.validate("engine_rpm", 850.0, "rpm", time.time())
        assert sig2.quality == SignalQuality.STALE


class TestNormalizedTelemetrySample:
    def test_boost_calculation(self):
        sample = NormalizedTelemetrySample(
            timestamp=time.time(),
            map_kpa=201.3,
            baro_kpa=101.3,
        )
        sample.compute_derived_metrics()
        # 100 kPa over atmospheric * 0.145038 = 14.50 psi
        assert sample.boost_psi == pytest.approx(14.50, abs=0.05)
        assert sample.manifold_vacuum_inhg == 0.0

    def test_vacuum_calculation(self):
        sample = NormalizedTelemetrySample(
            timestamp=time.time(),
            map_kpa=35.0,
            baro_kpa=101.3,
        )
        sample.compute_derived_metrics()
        assert sample.boost_psi == 0.0
        # (101.3 - 35.0) * 0.295300 = 19.58 inHg
        assert sample.manifold_vacuum_inhg == pytest.approx(19.58, abs=0.05)

    def test_afr_error_calculation(self):
        sample = NormalizedTelemetrySample(
            timestamp=time.time(),
            target_afr=12.5,
            afr_measured=13.5,  # 1.0 AFR lean
        )
        sample.compute_derived_metrics()
        # ((13.5 - 12.5) / 12.5) * 100 = +8.0%
        assert sample.afr_error_pct == pytest.approx(8.0, abs=0.01)

    def test_injector_duty_cycle(self):
        sample = NormalizedTelemetrySample(
            timestamp=time.time(),
            engine_rpm=6000.0,
            fuel_pw=15.0,
        )
        sample.compute_derived_metrics()
        # (6000 * 15) / 1200 = 75.0%
        assert sample.injector_duty_pct == 75.0

    def test_overall_quality_scoring(self):
        now = time.time()
        s1 = TelemetrySignal("rpm", 850.0, "rpm", now, quality=SignalQuality.VALID)
        s2 = TelemetrySignal("map", 35.0, "kPa", now, quality=SignalQuality.VALID)
        s3 = TelemetrySignal("tps", 0.0, "%", now, quality=SignalQuality.OUT_OF_RANGE)
        s4 = TelemetrySignal("clt", 185.0, "°F", now, quality=SignalQuality.VALID)

        sample = NormalizedTelemetrySample(
            timestamp=now,
            signals={"rpm": s1, "map": s2, "tps": s3, "clt": s4},
        )
        score = sample.calculate_quality_score()
        assert score == 0.75  # 3 of 4 valid
