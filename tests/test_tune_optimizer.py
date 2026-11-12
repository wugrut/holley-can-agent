"""Tests for the VE optimizer's safety/confidence behaviour, comparison, alerts and the file watcher."""

from __future__ import annotations

from holley_can.tune_optimizer import (
    AutoHandoffWatcher,
    PostPullDetector,
    VETableOptimizer,
    build_safety_alerts,
    compare_scorecards,
    worst_alert_level,
)


def _row(i: int, rpm: float = 4000.0, map_kpa: float = 150.0, afr: float = 13.5, target: float = 12.5) -> dict:
    return {
        "timestamp_s": 100.0 + i * 0.05,
        "rpm": rpm,
        "map_kpa": map_kpa,
        "tps": 60.0,
        "afr_avg": afr,
        "target_afr": target,
        "coolant_temp": 185.0,
        "closed_loop_comp": 0.0,
        "current_learn": 0.0,
        "baro_kpa": 101.325,
    }


def _feed(opt: VETableOptimizer, n: int, **kw) -> None:
    for i in range(n):
        opt.ingest_row(_row(i, **kw))


def _cell(payload: dict, map_kpa: int, rpm: int) -> dict:
    for row in payload["rows"]:
        if row["map_kpa"] == map_kpa:
            for c in row["cells"]:
                if c["rpm"] == rpm:
                    return c
    raise AssertionError("cell not found")


# ── Payload contract used by the web UI and the Gemini tools ────────────────

def test_payload_has_keys_ui_and_agent_depend_on():
    p = VETableOptimizer().get_matrix_payload()
    for key in ("rows", "holley_tsv_ve", "holley_tsv_correction_pct", "cells_populated",
                "last_source", "total_samples", "max_step_pct", "low_confidence_cells", "comparison"):
        assert key in p, key
    assert len(p["rows"]) == 16 and all(len(r["cells"]) == 16 for r in p["rows"])
    for key in ("rpm", "map_kpa", "hits", "base_ve", "recommended_ve", "correction_pct",
                "raw_correction_pct", "confidence", "limited"):
        assert key in p["rows"][0]["cells"][0], key


def test_export_holley_tsv_is_16_by_16():
    lines = VETableOptimizer().export_holley_tsv().split("\r\n")
    assert len(lines) == 16 and all(len(l.split("\t")) == 16 for l in lines)


# ── Per-pass limiter & confidence ───────────────────────────────────────────

def test_large_correction_is_capped_per_pass():
    opt = VETableOptimizer(max_step_pct=5.0, min_hits=5)
    _feed(opt, 40)
    c = _cell(opt.get_matrix_payload(), 150, 4000)
    assert c["hits"] >= 5
    assert c["raw_correction_pct"] > 5.0          # measured error is bigger than the cap
    assert c["correction_pct"] == 5.0              # but only 5% is applied
    assert c["limited"] is True
    assert c["recommended_ve"] == round(c["base_ve"] * 1.05, 1)


def test_thin_cells_are_left_unchanged():
    opt = VETableOptimizer(max_step_pct=5.0, min_hits=5)
    _feed(opt, 3)
    p = opt.get_matrix_payload()
    c = _cell(p, 150, 4000)
    assert 0 < c["hits"] < 5
    assert c["confidence"] == "low"
    assert c["correction_pct"] == 0.0
    assert c["recommended_ve"] == c["base_ve"]
    assert p["low_confidence_cells"] == 1


def test_small_correction_is_not_flagged_limited():
    opt = VETableOptimizer(max_step_pct=5.0, min_hits=5)
    _feed(opt, 40, afr=12.7)  # ~1.6% lean
    c = _cell(opt.get_matrix_payload(), 150, 4000)
    assert 0 < c["correction_pct"] < 5.0
    assert c["limited"] is False


# ── Before/after comparison ─────────────────────────────────────────────────

def test_table_comparison_detects_improvement():
    opt = VETableOptimizer()
    _feed(opt, 40, afr=13.5)                 # 8% lean
    assert opt.get_matrix_payload()["comparison"] is None
    opt._prev_snapshot = opt._snapshot()
    opt.reset()
    opt.last_source = "pass2.dl"
    _feed(opt, 40, afr=12.6)                 # ~0.8% lean
    cmp_ = opt.get_matrix_payload()["comparison"]
    assert cmp_["trend"] == "improving"
    assert cmp_["cells_compared"] == 1 and cmp_["cells_improved"] == 1


def test_pull_comparison_deltas():
    prev = {"log_name": "a", "peak_boost_psig": 14.0, "afr_error": 0.9, "min_differential_fuel_psi": 54.0}
    cur = {"log_name": "b", "peak_boost_psig": 15.0, "afr_error": 0.2, "min_differential_fuel_psi": 58.0}
    d = compare_scorecards(cur, prev)
    assert d["peak_boost_psig"] == 1.0 and d["afr_error"] == -0.7
    assert d["afr_error_improved"] is True


# ── Safety alerts ───────────────────────────────────────────────────────────

def test_clean_pull_has_no_alerts():
    card = {"peak_boost_psig": 14.0, "afr_error": 0.1, "min_differential_fuel_psi": 58.0,
            "max_knock_retard_deg": 0.0, "peak_rpm": 6200, "boost_limit_psi": 17.0,
            "max_injector_duty_pct": 70.0}
    assert build_safety_alerts(card) == []
    assert worst_alert_level([]) == "info"


def test_dangerous_pull_alerts_are_critical_and_sorted():
    card = {"peak_boost_psig": 16.0, "afr_error": 1.0, "min_differential_fuel_psi": 49.0,
            "max_knock_retard_deg": 2.0, "peak_rpm": 6200, "boost_limit_psi": 17.0,
            "max_injector_duty_pct": 88.0}
    alerts = build_safety_alerts(card)
    codes = {a["code"]: a["level"] for a in alerts}
    assert codes["lean_under_boost"] == "critical"
    assert codes["fuel_pressure_low"] == "critical"
    assert codes["knock"] == "warning"
    assert codes["injector_duty"] == "warning"
    assert worst_alert_level(alerts) == "critical"
    assert alerts[0]["level"] == "critical"  # worst first


def test_scorecard_carries_alerts():
    det = PostPullDetector()
    samples = [
        {"rpm": 5000 + i * 10, "map_kpa": 200.0, "baro_kpa": 101.325, "tps": 100.0,
         "afr_avg": 13.6, "target_afr": 11.8, "fuel_pressure": 45.0, "injector_duty": 70.0,
         "knock_retard": 0.0, "timestamp_s": float(i)}
        for i in range(10)
    ]
    card = det.build_scorecard(samples, duration_s=2.0)
    assert card["safety_level"] == "critical"
    assert {a["code"] for a in card["safety_alerts"]} >= {"lean_under_boost", "fuel_pressure_low"}


# ── Watcher: never parse a file that is still being written ────────────────

def test_watcher_waits_for_stable_file(tmp_path):
    w = AutoHandoffWatcher(listener=None, ve_optimizer=VETableOptimizer(), pull_detector=PostPullDetector())
    f = tmp_path / "pull.dl"
    f.write_bytes(b"x" * 100)
    assert w._is_stable(str(f)) is False      # first sighting
    assert w._is_stable(str(f)) is True       # unchanged since last poll
    f.write_bytes(b"x" * 500)                 # Holley is still appending
    assert w._is_stable(str(f)) is False
    assert w._is_stable(str(f)) is True


def test_watcher_ignores_empty_or_missing_files(tmp_path):
    w = AutoHandoffWatcher(listener=None, ve_optimizer=VETableOptimizer(), pull_detector=PostPullDetector())
    empty = tmp_path / "empty.dl"
    empty.write_bytes(b"")
    assert w._is_stable(str(empty)) is False
    assert w._is_stable(str(empty)) is False
    assert w._is_stable(str(tmp_path / "missing.dl")) is False

