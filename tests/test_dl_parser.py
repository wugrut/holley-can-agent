"""
test_dl_parser.py — Unit tests for the Holley .DL / .DLZ binary datalog engine.
"""

import struct
from pathlib import Path
import pytest

from holley_can.dl_parser import (
    HolleyDatalogParser,
    _byte_swap_4,
    decompress_dlz,
    discover_local_holley_files,
)


def _create_synthetic_v3_dl(tmp_path: Path, num_rows: int = 10) -> Path:
    """Create a valid Terminator X V3 2512-byte/row .dl binary file for testing."""
    header = bytearray(HolleyDatalogParser.V3_DATA_START)
    # Magic 0x0095365F, field_08 = 3
    struct.pack_into("<4I", header, 0, 0x0095365F, 0, 3, 1)
    cal_str = b"013 fuel 58 psi new antilag config.terx\x00"
    header[800:800 + len(cal_str)] = cal_str

    body = bytearray()
    for r in range(num_rows):
        row = bytearray(HolleyDatalogParser.V3_BYTES_PER_ROW)
        # Slot 0: timestamp ms
        struct.pack_into("<II", row, 0, 1000 + r * 25, 220)
        # Slot 1: RPM
        struct.pack_into("<fI", row, 1 * 8, 850.0 + r * 500.0, 33)
        # Slot 2: Inj PW
        struct.pack_into("<fI", row, 2 * 8, 2.2 + r * 0.6, 33)
        # Slot 3: Duty Cycle
        struct.pack_into("<fI", row, 3 * 8, 5.0 + r * 4.0, 33)
        # Slot 5: Target AFR
        struct.pack_into("<fI", row, 5 * 8, 12.8, 33)
        # Slot 7: AFR Avg
        struct.pack_into("<fI", row, 7 * 8, 12.7, 33)
        # Slot 25: Ignition Timing
        struct.pack_into("<fI", row, 25 * 8, 26.0, 33)
        # Slot 31: MAP kPa
        struct.pack_into("<fI", row, 31 * 8, 45.0 + r * 12.0, 33)
        # Slot 32: TPS %
        struct.pack_into("<fI", row, 32 * 8, 100.0 if r >= 5 else 10.0, 33)
        # Slot 34: Coolant Temp
        struct.pack_into("<fI", row, 34 * 8, 192.0, 33)
        # Slot 36: Battery V
        struct.pack_into("<fI", row, 36 * 8, 14.1, 33)
        # Slot 38: Fuel Pressure psi
        struct.pack_into("<fI", row, 38 * 8, 58.0, 33)
        body.extend(row)

    dl_file = tmp_path / "test_pull.dl"
    dl_file.write_bytes(bytes(header + body))
    return dl_file


class TestHolleyDatalogParser:
    def test_byte_swap_roundtrip(self):
        original = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        swapped = _byte_swap_4(original)
        assert swapped == b"\x04\x03\x02\x01\x08\x07\x06\x05"
        assert _byte_swap_4(swapped) == original

    def test_synthetic_v3_dl_parse_and_summarize(self, tmp_path: Path):
        dl_path = _create_synthetic_v3_dl(tmp_path, num_rows=10)
        parser = HolleyDatalogParser(dl_path)

        summary = parser.summarize()
        assert summary["num_rows"] == 10
        assert summary["version"] == "V3 (Terminator X)"
        assert "013" in summary["embedded_tune"] or summary["embedded_tune"].endswith(".terx")
        assert summary["channels"]["rpm"]["max"] == pytest.approx(5350.0, rel=1e-3)
        assert summary["channels"]["fuel_pressure"]["avg"] == pytest.approx(58.0, rel=1e-3)
        assert summary["wot_analysis"]["wot_samples"] == 5
        assert summary["wot_analysis"]["peak_rpm"] == 5350.0

        frames = parser.to_decoded_frames()
        assert len(frames) >= 10
        rpm_frame = next(f for f in frames if f.name == "rpm")
        assert rpm_frame.value_a == pytest.approx(5350.0, rel=1e-3)

    def test_real_terminator_x_sample_datalog_if_present(self):
        sample_dl = (
            Path.home()
            / "OneDrive"
            / "Documents"
            / "Holley"
            / "Terminator X V3"
            / "Data Logs"
            / "sample data log.dl"
        )
        if not sample_dl.exists():
            pytest.skip("Local Terminator X V3 sample data log.dl not present")

        parser = HolleyDatalogParser(sample_dl)
        summary = parser.summarize()
        assert summary["num_rows"] == 1003
        assert summary["duration_s"] == pytest.approx(24.98, abs=0.1)
        assert summary["channels"]["rpm"]["max"] > 5800.0
        assert summary["wot_analysis"]["wot_samples"] > 100

    def test_ve_table_optimizer_and_post_pull_detector(self, tmp_path: Path):
        from holley_can.tune_optimizer import (
            VETableOptimizer,
            PostPullDetector,
            compute_4l80e_converter_metrics,
            compute_manifold_referenced_fuel_metrics,
            estimate_wideband_transport_delay_s,
            is_sloppy_transbrake_staging,
        )

        # Verify 1:1 manifold/boost-referenced fuel pressure across vacuum AND boost:
        # At 45 kPa vacuum (-8.17 psig), rail is 49.83 psig -> differential across injector tip is 58.0 psi!
        vac_fp = compute_manifold_referenced_fuel_metrics(fuel_psi_gauge=49.83, map_kpa=45.0, baro_kpa=101.325, base_fuel_psi=58.0)
        assert vac_fp["differential_psi"] == pytest.approx(58.0, abs=0.1)
        assert vac_fp["fp_drop"] is False

        # At +15.0 psi boost (204.75 kPa), rail rises 1:1 to 73.0 psig -> differential is STILL 58.0 psi!
        boost_fp = compute_manifold_referenced_fuel_metrics(fuel_psi_gauge=73.0, map_kpa=204.75, baro_kpa=101.325, base_fuel_psi=58.0)
        assert boost_fp["differential_psi"] == pytest.approx(58.0, abs=0.1)
        assert boost_fp["fp_drop"] is False

        # Verify spooling pull (0 psi boost @ 58 psig rail -> +15 psi boost @ 73 psig rail) has zero false FP drop alerts:
        detector = PostPullDetector(base_fuel_psi=58.0)
        spool_pull = [
            {"rpm": 3200.0, "map_kpa": 101.325, "baro_kpa": 101.325, "tps": 100.0, "fuel_pressure": 58.0, "afr_avg": 11.8, "target_afr": 11.8},
            {"rpm": 4500.0, "map_kpa": 156.48,  "baro_kpa": 101.325, "tps": 100.0, "fuel_pressure": 66.0, "afr_avg": 11.6, "target_afr": 11.6},
            {"rpm": 6000.0, "map_kpa": 204.75,  "baro_kpa": 101.325, "tps": 100.0, "fuel_pressure": 73.0, "afr_avg": 11.5, "target_afr": 11.5},
        ]
        spool_card = detector.build_scorecard(spool_pull, duration_s=3.5)
        assert spool_card["fuel_pressure_ok"] is True
        assert spool_card["min_differential_fuel_psi"] == pytest.approx(58.0, abs=0.1)
        assert spool_card["fp_at_peak_boost_psi"] == pytest.approx(73.0, abs=0.1)

        # Verify velocity-dependent Wideband O2 transport delay (100ms - 150ms)
        idle_lag = estimate_wideband_transport_delay_s(rpm=850.0, map_kpa=45.0)
        wot_lag = estimate_wideband_transport_delay_s(rpm=6200.0, map_kpa=220.0)
        assert 0.145 <= idle_lag <= 0.150
        assert 0.100 <= wot_lag <= 0.105

        # Verify 3rd-gear "Sloppy Transbrake" staging detection & exclusion
        staging_row = {
            "timestamp_s": 1.0,
            "rpm": 3100.0,
            "map_kpa": 145.0,
            "tps": 95.0,
            "ignition_timing": 3.5,
            "trans_gear": 3.0,
            "vehicle_speed": 0.0,
            "coolant_temp": 185.0,
            "afr_avg": 11.8,
            "target_afr": 11.8,
        }
        assert is_sloppy_transbrake_staging(staging_row) is True

        # Verify 4L80E + Yank 3600 converter slip calculation (3.73:1 rear + 25.85" tire)
        pull_row = {
            "rpm": 5800.0,
            "trans_gear": 3.0,          # 1.00:1 in 4L80E
            "vehicle_speed": 108.0,     # ~5422 RPM driveshaft -> ~6.5% converter slip
            "tcc_status": 0.0,
            "lockup_status": 0.0,
        }
        conv = compute_4l80e_converter_metrics(pull_row)
        assert conv["gear"] == 3
        assert conv["converter_locked"] is False
        assert 4.0 <= conv["converter_slip_pct"] <= 10.0

        # Verify transient dTPS/dt and cold coolant filtering + New_VE mathematical formula
        # This test verifies the raw VE formula, so disable the per-pass cap and confidence gate
        # (those are covered in test_tune_optimizer.py).
        opt = VETableOptimizer(base_fuel_psi=58.0, min_coolant_f=160.0, max_step_pct=20.0, min_hits=1)
        # Cold sample (145°F < 160°F) -> rejected
        assert opt.ingest_row({
            "timestamp_s": 1.0, "rpm": 2000.0, "map_kpa": 60.0, "tps": 20.0,
            "coolant_temp": 145.0, "afr_avg": 14.2, "target_afr": 14.0, "closed_loop_comp": 5.0,
        }) is False
        assert opt.cold_rejected_samples == 1

        # Steady warm sample (185°F) with +10% CL_Comp on 60.0% Base VE -> New_VE = 60.0 * 1.10 = 66.0%
        assert opt.ingest_row({
            "timestamp_s": 2.0, "rpm": 2000.0, "map_kpa": 60.0, "tps": 20.0,
            "coolant_temp": 185.0, "afr_avg": 14.0, "target_afr": 14.0,
            "closed_loop_comp": 10.0, "base_fuel_ve": 60.0, "fuel_pressure": 58.0,
        }) is True

        # Violent TPS spike (+50% in 0.05s = 1000 %/s > 25 %/s threshold) -> rejected
        assert opt.ingest_row({
            "timestamp_s": 2.05, "rpm": 2100.0, "map_kpa": 95.0, "tps": 70.0,
            "coolant_temp": 185.0, "afr_avg": 12.8, "target_afr": 12.8,
            "closed_loop_comp": 15.0, "base_fuel_ve": 70.0, "fuel_pressure": 58.0,
        }) is False
        assert opt.transient_rejected_samples == 1

        matrix = opt.get_matrix_payload()
        assert matrix["total_samples"] == 1
        assert matrix["cells_touched"] == 1
        # Locate the 60 kPa / 2000 RPM cell and verify New_VE = 60.0 * (1 + 10/100) = 66.0
        row_60 = next(r for r in matrix["rows"] if r["map_kpa"] == 60)
        cell_2000 = next(c for c in row_60["cells"] if c["rpm"] == 2000)
        assert cell_2000["recommended_ve"] == pytest.approx(66.0, abs=0.1)

        dl_path = _create_synthetic_v3_dl(tmp_path, num_rows=20)
        parser = HolleyDatalogParser(dl_path)
        rows = parser.parse_rows(max_rows=20)

        detector = PostPullDetector(base_fuel_psi=58.0)
        scorecard = detector.build_scorecard(rows, duration_s=5.0)
        assert scorecard is not None
        assert scorecard["peak_rpm"] > 5000.0
        assert scorecard["severity"] in ("info", "warning", "critical")


