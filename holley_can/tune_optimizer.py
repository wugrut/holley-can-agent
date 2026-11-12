"""
tune_optimizer.py — Fairmont VE Optimizer, 4L80E Drivetrain/Staging Auditor & Auto-Handoff Engine

Target Platform: 1980 Ford Fairmont 4-Door "Boxtop" (Fox Platform, ~3,300 lbs)
Engine:          GM 4.8L Iron-Block Gen III LS (LM7/LR4), Elgin E-1840-P "Sloppy Stage 2" Cam
                 (228°/230° @ .050", .585"/.585" lift, 112° LSA), PAC 1218 springs
Induction:       VS Racing 78/75 Turbo on Hooker BlackHeart manifold, 3" Cold Side FMIC,
                 Pre-TB BOV, 3" exhaust w/ 3" electric cutout, NGK BR7EF @ 0.022"
Fueling:         Racetronix 420 LPH pump, 58 PSI base mechanical rail pressure (1:1 boost-ref),
                 Siemens Deka 80 lb/hr High-Z injectors, Flex Fuel sensor (E85 / 93 / E40)
Transmission:    GM 4L80E (Alto Red Eagle / TransGo HD2), Yank 3600 RPM stall converter,
                 3rd-gear mechanical bind-up "Sloppy Transbrake" staging (3000–3200 RPM @ 0°–5° BTDC),
                 Ford 8.8" rear axle w/ 3.73:1 gears, 245/45R17 drag radials (~25.85" rolling dia)
ECU & Bus:       Holley Terminator X Max EFI @ 1 Mbps CAN (can0 SocketCAN / Holley USB-CAN / PCAN / SLCAN)
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine, Deque, Dict, List, Optional

from .dl_parser import HolleyDatalogParser, discover_local_holley_files
from .terx_parser import TerxCalibration, discover_terx_files

logger = logging.getLogger(__name__)

# ─── 1980 Ford Fairmont Turbo LS Platform Specification ─────────────────────

FAIRMONT_PLATFORM_SPEC: Dict[str, Any] = {
    "vehicle": "1980 Ford Fairmont 4-Door 'Boxtop' (Fox Platform)",
    "curb_weight_lbs": 3300,
    "rear_axle": "Ford 8.8-inch SN95 (3.73:1 ring & pinion)",
    "final_drive_ratio": 3.73,
    "tire_size": "245/45R17 Drag Radials",
    "tire_diameter_in": 25.85,
    "engine": "GM 4.8L Gen III LS (LM7/LR4)",
    "camshaft": "Elgin E-1840-P Sloppy Stage 2 (228/230 @ .050, .585/.585, 112 LSA) + PAC 1218",
    "turbo": "VS Racing 78/75 on Hooker BlackHeart Manifold + 3in FMIC",
    "ignition": "Stock LS CNP + NGK BR7EF @ 0.022in",
    "fuel_system": "Racetronix 420 LPH + 58 PSI Base (1:1 Boost-Ref) + Siemens Deka 80 lb/hr + Flex Fuel",
    "transmission": "GM 4L80E (Alto Red Eagle, TransGo HD2) + Yank 3600 RPM Stall",
    "gear_ratios_4l80e": {1: 2.48, 2: 1.48, 3: 1.00, 4: 0.75},
    "staging_strategy": "3rd-Gear Mechanical Bind-Up 'Sloppy Transbrake' (3000-3200 RPM, 0-5 deg BTDC)",
    "limits": {
        "base_fuel_psi": 58.0,
        "standard_boost_min_psi": 12.0,
        "standard_boost_max_psi": 15.0,
        "pump_blend_boost_cut_psi": 17.0,   # > 17.0 PSI hard safety threshold on lower ethanol blends
        "max_e85_boost_psi": 20.0,          # 20.0 PSI strictly on high-percentage E85
        "max_rpm": 6800.0,
        "min_coolant_f": 160.0,             # Coolant temp > 160°F required for steady-state VE learning
        "steady_state_trim_target_pct": 2.0,
        "d_tps_threshold_pct_s": 25.0,      # Filter |dTPS/dt| > 25 %/sec
        "d_map_threshold_kpa_s": 65.0,      # Filter |dMAP/dt| > 65 kPa/sec
        "wb_lag_min_ms": 100.0,             # High exhaust velocity wideband O2 transport delay
        "wb_lag_max_ms": 150.0,             # Low exhaust velocity wideband O2 transport delay
    },
}

# Standard 16x16 3-Bar Turbo LS Breakpoints (500 to 7000 RPM vs 20 to 260 kPa MAP)
RPM_AXIS: List[int] = [
    500, 800, 1200, 1600, 2000, 2400, 2800, 3200,
    3600, 4000, 4500, 5000, 5500, 6000, 6500, 7000,
]

MAP_AXIS: List[int] = [
    20, 30, 40, 50, 60, 70, 80, 90,
    100, 115, 130, 150, 175, 200, 230, 260,
]


def _nearest_index(axis: List[int], val: float) -> int:
    best_i = 0
    best_dist = abs(val - axis[0])
    for i in range(1, len(axis)):
        d = abs(val - axis[i])
        if d < best_dist:
            best_dist = d
            best_i = i
    return best_i


def compute_manifold_referenced_fuel_metrics(
    fuel_psi_gauge: float,
    map_kpa: float,
    baro_kpa: float = 101.325,
    base_fuel_psi: float = 58.0,
) -> Dict[str, float | bool]:
    """
    Computes 1:1 manifold/boost-referenced fuel pressure metrics for a single sample.

    With a 1:1 vacuum/boost-referenced regulator set to 58.0 PSI base (hose off):
      - Manifold Gauge Pressure (PSIG) = (MAP_kPa - Baro_kPa) * 0.145038
        (negative in vacuum, 0 at atmospheric, positive in boost)
      - Expected Rail Gauge Pressure (PSIG) = 58.0 + Manifold_PSIG
        (e.g., ~49.8 PSIG at 45 kPa idle vacuum, 58.0 PSIG at 101.3 kPa, 73.0 PSIG at +15 PSI boost)
      - Injector Differential Pressure (dP_inj) = Rail_PSIG - Manifold_PSIG
        (should remain constant at ~58.0 PSI across ALL vacuum and boost cells!)
      - Injector Flow Ratio = sqrt(dP_inj / 58.0)
    """
    baro = baro_kpa if baro_kpa > 50.0 else 101.325
    manifold_psig = (map_kpa - baro) * 0.145038
    expected_rail_psig = base_fuel_psi + manifold_psig

    # If no fuel pressure sensor is active (< 15 PSI), assume ideal 1:1 tracking (dP = 58.0 PSI)
    sensor_active = fuel_psi_gauge >= 15.0
    if sensor_active:
        diff_psi = fuel_psi_gauge - manifold_psig
        dp_error_psi = diff_psi - base_fuel_psi  # negative = pressure sag below 58 PSI differential
        flow_ratio = math.sqrt(max(10.0, diff_psi) / base_fuel_psi)
        # Flag warning if differential pressure across injector tip drops > 6.0 PSI below 58.0 PSI (< 52.0 PSI dP)
        fp_drop = dp_error_psi < -6.0
    else:
        diff_psi = base_fuel_psi
        dp_error_psi = 0.0
        flow_ratio = 1.0
        fp_drop = False

    return {
        "manifold_psig": round(manifold_psig, 2),
        "expected_rail_psig": round(expected_rail_psig, 2),
        "rail_psig": round(fuel_psi_gauge, 2),
        "differential_psi": round(diff_psi, 2),
        "dp_error_psi": round(dp_error_psi, 2),
        "injector_flow_ratio": round(flow_ratio, 4),
        "fp_drop": fp_drop,
    }


def estimate_wideband_transport_delay_s(rpm: float, map_kpa: float) -> float:
    """
    Computes wideband O2 sensor exhaust transport delay (100ms to 150ms) as a function
    of exhaust gas velocity proxy (RPM * MAP_kPa) through the Hooker BlackHeart manifold
    and VS Racing 78/75 turbine housing.
      - Idle / low-flow cruise (~800 RPM * 45 kPa = 36,000): ~0.150 s (150 ms)
      - High-RPM WOT boost (~6000 RPM * 215 kPa = 1,290,000): ~0.100 s (100 ms)
    """
    flow_proxy = max(0.0, rpm * map_kpa)
    norm = max(0.0, min(1.0, (flow_proxy - 40_000.0) / 1_200_000.0))
    return round(0.150 - (0.050 * norm), 4)


def is_sloppy_transbrake_staging(row: Dict[str, float]) -> bool:
    """
    Detects when the Fairmont 4L80E is engaged in the 3rd-gear mechanical bind-up
    "Sloppy Transbrake" staging strategy (3000-3200 RPM on the 2-step limiter with
    2D ignition timing retard to 0°-5° BTDC and vehicle stationary).
    """
    if (
        row.get("trans_brake_status", 0.0) > 0.5
        or row.get("launch_status", 0.0) > 0.5
        or row.get("rev_limit_1", 0.0) > 0.5
        or row.get("staging_input_1", 0.0) > 0.5
    ):
        return True

    gear = int(round(row.get("trans_gear", 0.0)))
    speed = row.get("vehicle_speed", 0.0)
    rpm = row.get("rpm", 0.0)
    timing = row.get("ignition_timing", 20.0)
    tps = row.get("tps", 0.0)

    # 3rd-gear bind-up hold @ 2700-3500 RPM, stationary (< 3 mph), high throttle or 0-6° timing retard
    if speed < 3.0 and 2700.0 <= rpm <= 3550.0:
        if gear == 3 and (tps >= 40.0 or timing <= 7.0):
            return True
        if tps >= 65.0 and -5.0 <= timing <= 6.5:
            return True
    return False


def compute_4l80e_converter_metrics(row: Dict[str, float]) -> Dict[str, Any]:
    """
    Evaluates GM 4L80E gear state, TCC lockup bit, and Yank 3600 RPM converter slip %
    using the Fairmont's 3.73:1 Ford 8.8" rear end and 25.85" (245/45R17) drag radials.
    """
    gear = int(round(row.get("trans_gear", 0.0)))
    rpm = row.get("rpm", 0.0)
    mph = row.get("vehicle_speed", 0.0)
    input_rpm = row.get("input_speed", 0.0)
    tcc_dc = row.get("tcc_status", 0.0)
    lockup_bit = row.get("lockup_status", 0.0) > 0.5 or tcc_dc >= 85.0

    gear_ratios = FAIRMONT_PLATFORM_SPEC["gear_ratios_4l80e"]
    gear_ratio = gear_ratios.get(gear, 1.00)
    final_drive = FAIRMONT_PLATFORM_SPEC["final_drive_ratio"]     # 3.73
    tire_dia = FAIRMONT_PLATFORM_SPEC["tire_diameter_in"]         # 25.85"

    # Calculate theoretical turbine/driveshaft RPM if input_speed sensor is not populated
    if input_rpm > 100.0:
        turbine_rpm = input_rpm
    elif mph > 3.0 and gear in gear_ratios:
        # RPM = (MPH * Gear_Ratio * Final_Drive * 336.13) / Tire_Diameter_Inches
        turbine_rpm = (mph * gear_ratio * final_drive * 336.135) / tire_dia
    else:
        turbine_rpm = 0.0

    if rpm > 1000.0 and turbine_rpm > 100.0 and rpm >= turbine_rpm:
        slip_rpm = rpm - turbine_rpm
        slip_pct = (slip_rpm / rpm) * 100.0
    else:
        slip_rpm = 0.0
        slip_pct = 0.0

    return {
        "gear": gear,
        "converter_locked": bool(lockup_bit),
        "tcc_duty_pct": round(tcc_dc, 1),
        "turbine_rpm": round(turbine_rpm, 0),
        "converter_slip_rpm": round(slip_rpm, 0),
        "converter_slip_pct": round(slip_pct, 1),
        "sloppy_transbrake_active": is_sloppy_transbrake_staging(row),
    }


@dataclass
class _HistoryState:
    """Historical engine operating state for Wideband O2 transport delay alignment."""
    timestamp_s: float
    rpm: float
    map_kpa: float
    tps: float
    base_ve: float
    fuel_psi: float
    diff_fuel_psi: float
    knock: float
    fp_drop: bool
    is_steady: bool


@dataclass
class VECellAccumulator:
    """Accumulates steady-state, transport-delay-aligned telemetry hits for a (MAP, RPM) cell."""
    hits: int = 0
    sum_afr: float = 0.0
    sum_target_afr: float = 0.0
    sum_cl_comp: float = 0.0
    sum_learn: float = 0.0
    sum_base_ve: float = 0.0
    sum_fuel_psi: float = 0.0
    sum_diff_fuel_psi: float = 0.0
    sum_knock: float = 0.0
    fuel_psi_drop_hits: int = 0

    def add_sample(
        self,
        afr: float,
        target_afr: float,
        cl_comp: float,
        learn: float,
        base_ve: float,
        fuel_psi: float,
        diff_fuel_psi: float,
        knock: float,
        fp_drop: bool,
    ) -> None:
        self.hits += 1
        self.sum_afr += afr
        self.sum_target_afr += target_afr
        self.sum_cl_comp += cl_comp
        self.sum_learn += learn
        self.sum_base_ve += base_ve
        self.sum_fuel_psi += fuel_psi
        self.sum_diff_fuel_psi += diff_fuel_psi
        self.sum_knock += knock
        if fp_drop:
            self.fuel_psi_drop_hits += 1


class VETableOptimizer:
    """
    Fairmont VE Optimizer (16x16 RPM 500..7000 vs MAP 20..260 kPa).

    Implements:
      - Coolant Temp > 160°F verification
      - DFCO (Decel Fuel Cutoff) exclusion
      - Transient TPS/MAP rate-of-change rejection (|dTPS/dt| > 25%/s, |dMAP/dt| > 65 kPa/s)
      - 3rd-gear "Sloppy Transbrake" staging exclusion
      - Wideband O2 transport delay time-shift (100–150 ms velocity-dependent lookback)
      - Exact mathematical VE correction: New_VE = Current_VE * (1.0 + (CL_Comp_Percent / 100.0))
        targeting steady-state closed-loop trim error within ±2.0%.
    """

    def __init__(
        self,
        base_fuel_psi: float = 58.0,
        min_coolant_f: float = 160.0,
        d_tps_threshold: float = 25.0,
        d_map_threshold: float = 65.0,
        steady_trim_target_pct: float = 2.0,
        max_step_pct: float = 5.0,
        min_hits: int = 5,
    ):
        self.base_fuel_psi = base_fuel_psi
        self.min_coolant_f = min_coolant_f
        self.d_tps_threshold = d_tps_threshold
        self.d_map_threshold = d_map_threshold
        self.steady_trim_target_pct = steady_trim_target_pct
        # Per-pass correction limiter: no cell is moved more than +/- max_step_pct in one pass,
        # and cells with fewer than min_hits steady-state samples are left unchanged.
        self.max_step_pct = max_step_pct
        self.min_hits = min_hits
        # Snapshot of the previously loaded log's corrections, for before/after comparison.
        self._loaded_name: Optional[str] = None
        self._prev_snapshot: Optional[Dict[str, Any]] = None
        self.tune_history: List[Dict[str, Any]] = []
        self.loaded_terx_path: Optional[str] = None
        self.loaded_terx_comment: Optional[str] = None

        self.rpm_axis = list(RPM_AXIS)
        self.map_axis = list(MAP_AXIS)
        self.grid: List[List[VECellAccumulator]] = [
            [VECellAccumulator() for _ in range(16)] for _ in range(16)
        ]
        self.total_samples_ingested = 0
        self.filtered_samples = 0
        self.transient_rejected_samples = 0
        self.dfco_rejected_samples = 0
        self.cold_rejected_samples = 0
        self.staging_rejected_samples = 0
        self.enrichment_rejected_samples = 0
        self.last_source: str = "live"

        # State for rate-of-change (dTPS/dt, dMAP/dt) & wideband transport delay buffer
        self._prev_ts: Optional[float] = None
        self._prev_tps: Optional[float] = None
        self._prev_map: Optional[float] = None
        self._history_buffer: Deque[_HistoryState] = deque(maxlen=64)

        # Seed default 4.8L LS + Sloppy Stage 2 + VS Racing 78/75 Base VE curve
        self.default_base_ve: List[List[float]] = self._build_default_base_ve()

    def _build_default_base_ve(self) -> List[List[float]]:
        """
        Seeds a realistic 4.8L LS + Elgin E-1840-P Sloppy Stage 2 (228/230) Base VE table:
        Slightly lower vacuum idle VE (~40-46%) due to 112° LSA overlap, ramping strongly
        into peak torque/boost (4400-5800 RPM) with the VS Racing 78/75 turbo.
        """
        table: List[List[float]] = []
        for m_idx, map_val in enumerate(self.map_axis):
            row: List[float] = []
            load_factor = (map_val - 20.0) / 240.0
            for r_idx, rpm_val in enumerate(self.rpm_axis):
                rpm_curve = 1.0 - abs(rpm_val - 5000.0) / 9200.0
                ve = (36.0 + load_factor * 54.0) * rpm_curve + (load_factor * 15.0)
                row.append(round(max(25.0, min(128.0, ve)), 1))
            table.append(row)
        return table

    def reset(self) -> None:
        self.grid = [[VECellAccumulator() for _ in range(16)] for _ in range(16)]
        self.total_samples_ingested = 0
        self.filtered_samples = 0
        self.transient_rejected_samples = 0
        self.dfco_rejected_samples = 0
        self.cold_rejected_samples = 0
        self.staging_rejected_samples = 0
        self.enrichment_rejected_samples = 0
        self._prev_ts = None
        self._prev_tps = None
        self._prev_map = None
        self._history_buffer.clear()

    def save_revision(self, note: str = "") -> Dict[str, Any]:
        """Saves a restorable snapshot of the current VE matrix to tune_history."""
        if self.total_samples_ingested == 0:
            return {}
        rev_id = f"rev_{len(self.tune_history) + 1}_{int(time.time())}"
        payload = self.get_matrix_payload(include_learn=True, include_comparison=False)
        grid_data = [
            [
                {
                    "hits": cell.hits,
                    "sum_afr": cell.sum_afr,
                    "sum_target_afr": cell.sum_target_afr,
                    "sum_cl_comp": cell.sum_cl_comp,
                    "sum_learn": cell.sum_learn,
                    "sum_base_ve": cell.sum_base_ve,
                    "sum_fuel_psi": cell.sum_fuel_psi,
                    "sum_diff_fuel_psi": cell.sum_diff_fuel_psi,
                    "sum_knock": cell.sum_knock,
                    "fuel_psi_drop_hits": cell.fuel_psi_drop_hits,
                }
                for cell in row
            ]
            for row in self.grid
        ]
        rev = {
            "id": rev_id,
            "timestamp": time.time(),
            "source": self.last_source,
            "note": note,
            "cells_populated": payload.get("cells_populated", 0),
            "total_samples": self.total_samples_ingested,
            "grid_data": grid_data,
        }
        self.tune_history.append(rev)
        if len(self.tune_history) > 20:
            self.tune_history.pop(0)
        return rev

    def revert_to_revision(self, rev_id: str) -> Optional[Dict[str, Any]]:
        """Restores the VE table and accumulators from a historical revision."""
        target_rev = next((r for r in self.tune_history if r["id"] == rev_id), None)
        if not target_rev:
            return None
        self.reset()
        grid_data = target_rev.get("grid_data", [])
        for m_idx in range(min(16, len(grid_data))):
            for r_idx in range(min(16, len(grid_data[m_idx]))):
                d = grid_data[m_idx][r_idx]
                acc = self.grid[m_idx][r_idx]
                acc.hits = d["hits"]
                acc.sum_afr = d["sum_afr"]
                acc.sum_target_afr = d["sum_target_afr"]
                acc.sum_cl_comp = d["sum_cl_comp"]
                acc.sum_learn = d["sum_learn"]
                acc.sum_base_ve = d["sum_base_ve"]
                acc.sum_fuel_psi = d["sum_fuel_psi"]
                acc.sum_diff_fuel_psi = d["sum_diff_fuel_psi"]
                acc.sum_knock = d["sum_knock"]
                acc.fuel_psi_drop_hits = d["fuel_psi_drop_hits"]
        self.total_samples_ingested = target_rev.get("total_samples", 0)
        self.last_source = f"{target_rev.get('source', 'unknown')} (Reverted to {rev_id})"
        return self.get_matrix_payload()

    def load_terx_tune(self, filepath_or_bytes: Union[str, Path, bytes, bytearray]) -> TerxCalibration:
        """
        Load a Holley .terx calibration directly into the optimizer.
        Updates self.rpm_axis, self.map_axis, and self.default_base_ve to match the vehicle's exact tune.
        """
        if isinstance(filepath_or_bytes, (bytes, bytearray)):
            cal = TerxCalibration.from_bytes(filepath_or_bytes)
        else:
            cal = TerxCalibration.from_file(filepath_or_bytes)

        if len(cal.rpm_axis) == 16 and len(cal.map_axis) == 16 and len(cal.ve_table) == 16:
            self.rpm_axis = [int(round(x)) for x in cal.rpm_axis]
            self.map_axis = [int(round(x)) for x in cal.map_axis]
            self.default_base_ve = [[round(cell, 2) for cell in row] for row in cal.ve_table]
            self.loaded_terx_path = str(cal.filepath) if cal.filepath else None
            self.loaded_terx_comment = cal.tune_comment or (cal.filepath.name if cal.filepath else "Loaded .terx")
            # Reset grid accumulators for the new calibration axis dimensions
            self.grid = [[VECellAccumulator() for _ in range(16)] for _ in range(16)]
            self.total_samples_ingested = 0
            self.last_source = f"TERX: {cal.filepath.name if cal.filepath else 'custom'}"
            self.save_revision()

        return cal

    def export_to_terx(
        self,
        target_path: Union[str, Path],
        source_path: Optional[Union[str, Path]] = None,
        include_learn: bool = True,
    ) -> TerxCalibration:
        """
        Export the recommended VE table directly into a .terx calibration file.
        If source_path is omitted, uses the previously loaded .terx path.
        """
        src = source_path or self.loaded_terx_path
        if not src:
            raise ValueError("No source .terx calibration specified or previously loaded")

        cal = TerxCalibration.from_file(src)
        payload = self.get_matrix_payload(include_learn=include_learn, include_comparison=False)

        # Build 16x16 matrix ordered by MAP ascending (0..15) as expected by TerxCalibration
        new_ve_grid = [[self.default_base_ve[m][r] for r in range(16)] for m in range(16)]
        for row in payload["rows"]:
            for cell in row["cells"]:
                m_val = cell["map_kpa"]
                r_val = cell["rpm"]
                m_idx = _nearest_index(self.map_axis, m_val)
                r_idx = _nearest_index(self.rpm_axis, r_val)
                new_ve_grid[m_idx][r_idx] = float(cell["recommended_ve"])

        cal.update_ve_table(new_ve_grid)
        cal.save(target_path)
        return cal

    def get_history(self) -> List[Dict[str, Any]]:
        """Returns summary list of past tune revisions (newest first)."""
        return [
            {
                "id": r["id"],
                "timestamp": r["timestamp"],
                "source": r["source"],
                "note": r["note"],
                "cells_populated": r["cells_populated"],
                "total_samples": r["total_samples"],
            }
            for r in reversed(self.tune_history)
        ]

    def ingest_row(self, row: Dict[str, float], allow_cold: bool = False) -> bool:
        """
        Ingests a single telemetry row (from live CAN snapshot or .dl datalog),
        performing transient dTPS/dt & dMAP/dt rejection and Wideband O2 transport
        delay alignment (100-150 ms lookback).
        """
        now_ts = float(row.get("timestamp_s") or row.get("timestamp") or time.time())
        rpm = row.get("rpm", 0.0)
        map_kpa = row.get("map_kpa", 0.0)
        tps = row.get("tps", 0.0)
        afr = row.get("afr_avg") or row.get("afr_left") or 0.0
        target_afr = row.get("target_afr", 0.0)
        clt = row.get("coolant_temp", 185.0)
        cl_comp = row.get("closed_loop_comp", 0.0)
        learn = row.get("current_learn", 0.0)
        fuel_psi = row.get("fuel_pressure", self.base_fuel_psi)
        baro = row.get("baro_kpa", 101.325) or 101.325
        knock = row.get("knock_retard", 0.0)
        fuel_pw = row.get("fuel_pw", 2.5)

        # 1. Compute dTPS/dt (%/s) and dMAP/dt (kPa/s)
        d_tps_dt = row.get("tps_roc")
        d_map_dt = row.get("map_roc")
        if (d_tps_dt is None or d_map_dt is None) and self._prev_ts is not None:
            dt = now_ts - self._prev_ts
            if 0.002 <= dt <= 1.0:
                if d_tps_dt is None and self._prev_tps is not None:
                    d_tps_dt = (tps - self._prev_tps) / dt
                if d_map_dt is None and self._prev_map is not None:
                    d_map_dt = (map_kpa - self._prev_map) / dt
            elif dt < 0:
                # Reset history if timestamps jumped backwards (e.g. new file)
                self._history_buffer.clear()

        self._prev_ts = now_ts
        self._prev_tps = tps
        self._prev_map = map_kpa

        d_tps_abs = abs(d_tps_dt) if d_tps_dt is not None else 0.0
        d_map_abs = abs(d_map_dt) if d_map_dt is not None else 0.0
        is_transient = (d_tps_abs > self.d_tps_threshold) or (d_map_abs > self.d_map_threshold)

        # 2. Basic sanity & engine running check
        if rpm < 400.0 or map_kpa < 15.0:
            self.filtered_samples += 1
            return False

        # 3. Verify Coolant Temp > 160°F (per Fairmont VE Optimizer spec)
        if not allow_cold and (0.1 < clt < self.min_coolant_f):
            self.filtered_samples += 1
            self.cold_rejected_samples += 1
            return False

        # 3b. Exclude temporary ECU enrichments (Afterstart Enrichment, Warmup Coolant Enrichment, Coolant AFR Offset)
        # In Holley EFI, enrichments report either 0.0% (delta) or 100.0% (multiplier) when inactive.
        afterstart = row.get("afterstart_enrich", 0.0)
        clt_enrich = row.get("coolant_enrich", 0.0)
        clt_afr_off = abs(row.get("coolant_afr_offset", 0.0))
        afterstart_active = (0.5 < abs(afterstart) < 99.0) or (abs(afterstart - 100.0) > 1.0 and afterstart > 90.0)
        clt_enrich_active = not allow_cold and (
            (0.5 < abs(clt_enrich) < 99.0) or (abs(clt_enrich - 100.0) > 1.0 and clt_enrich > 90.0) or (clt_afr_off > 0.15)
        )
        if afterstart_active or clt_enrich_active:
            self.filtered_samples += 1
            self.enrichment_rejected_samples += 1
            return False

        # 4. Exclude 3rd-Gear "Sloppy Transbrake" staging limiter samples from corrupting steady VE
        if is_sloppy_transbrake_staging(row):
            self.filtered_samples += 1
            self.staging_rejected_samples += 1
            return False

        # 5. Exclude DFCO (Decel Fuel Cutoff)
        if rpm > 1500.0 and tps < 1.5 and (afr > 16.0 or fuel_pw < 1.1):
            self.filtered_samples += 1
            self.dfco_rejected_samples += 1
            return False

        # Record current engine state in the wideband transport delay lookback ring buffer
        m_idx_now = _nearest_index(self.map_axis, map_kpa)
        r_idx_now = _nearest_index(self.rpm_axis, rpm)
        base_ve_now = (
            row.get("base_fuel_ve")
            or row.get("estimated_ve")
            or self.default_base_ve[m_idx_now][r_idx_now]
        )

        # Evaluate 1:1 manifold/boost-referenced fuel pressure at this instant:
        # Expected Rail PSIG = 58.0 + Manifold_PSIG (across both vacuum and boost!),
        # so Differential Injector Pressure (Rail_PSIG - Manifold_PSIG) is always 58.0 PSI.
        baro = row.get("baro_kpa", 101.325) or 101.325
        manifold_psig_now = (map_kpa - baro) * 0.145038
        default_rail_psig = self.base_fuel_psi + manifold_psig_now
        raw_fp = row.get("fuel_pressure")
        fuel_psi = float(raw_fp) if (raw_fp is not None and raw_fp > 0.0) else default_rail_psig

        fp_metrics_now = compute_manifold_referenced_fuel_metrics(
            fuel_psi_gauge=fuel_psi,
            map_kpa=map_kpa,
            baro_kpa=baro,
            base_fuel_psi=self.base_fuel_psi,
        )
        diff_fp_now = float(fp_metrics_now["differential_psi"])
        fp_drop_now = bool(fp_metrics_now["fp_drop"])

        current_state = _HistoryState(
            timestamp_s=now_ts,
            rpm=rpm,
            map_kpa=map_kpa,
            tps=tps,
            base_ve=base_ve_now,
            fuel_psi=fuel_psi,
            diff_fuel_psi=diff_fp_now,
            knock=knock,
            fp_drop=fp_drop_now,
            is_steady=not is_transient,
        )
        self._history_buffer.append(current_state)

        # 6. Reject transient spikes (dTPS/dt or dMAP/dt above threshold)
        if is_transient:
            self.filtered_samples += 1
            self.transient_rejected_samples += 1
            return False

        # 7. Validate wideband O2 & Target AFR range
        if target_afr < 8.0 or target_afr > 20.0 or afr < 8.0 or afr > 20.0:
            self.filtered_samples += 1
            return False

        # 8. Wideband O2 Transport Delay Time-Shift (100-150 ms velocity-dependent lookback)
        lag_s = estimate_wideband_transport_delay_s(rpm, map_kpa)
        target_ts = now_ts - lag_s
        aligned_state = current_state
        best_dt = abs(current_state.timestamp_s - target_ts)
        for past in reversed(self._history_buffer):
            dt_err = abs(past.timestamp_s - target_ts)
            if dt_err <= best_dt and (now_ts - past.timestamp_s) <= 0.500:
                aligned_state = past
                best_dt = dt_err

        # If the historical state that generated this exhaust gas pulse was itself a transient spike, reject!
        if not aligned_state.is_steady:
            self.filtered_samples += 1
            self.transient_rejected_samples += 1
            return False

        m_idx = _nearest_index(self.map_axis, aligned_state.map_kpa)
        r_idx = _nearest_index(self.rpm_axis, aligned_state.rpm)

        self.grid[m_idx][r_idx].add_sample(
            afr=afr,
            target_afr=target_afr,
            cl_comp=cl_comp,
            learn=learn,
            base_ve=aligned_state.base_ve,
            fuel_psi=aligned_state.fuel_psi,
            diff_fuel_psi=aligned_state.diff_fuel_psi,
            knock=aligned_state.knock,
            fp_drop=aligned_state.fp_drop,
        )
        self.total_samples_ingested += 1
        return True

    def ingest_datalog(self, file_path: str | Path) -> Dict[str, Any]:
        """Parse an entire .dl or .dlz file and populate the 16x16 Fairmont VE matrix."""
        parser = HolleyDatalogParser(file_path)
        rows = parser.parse_rows()
        new_name = Path(file_path).name
        # Keep the previous distinct log's corrections so the UI can show a before/after comparison.
        # Re-ingesting the same file (e.g. it was re-saved) must not overwrite the baseline.
        if self.total_samples_ingested > 0 and self._loaded_name and self._loaded_name != new_name:
            self._prev_snapshot = self._snapshot()
        self._loaded_name = new_name
        self.reset()
        self.last_source = new_name
        # First try strict >160°F filter; if the log was a short warmup/shop test with 0 warm rows, fallback
        for r in rows:
            self.ingest_row(r, allow_cold=False)
        if self.total_samples_ingested == 0 and rows:
            self.reset()
            self.last_source = f"{Path(file_path).name} (cold override)"
            for r in rows:
                self.ingest_row(r, allow_cold=True)
        if self.total_samples_ingested > 0:
            self.save_revision()
        return self.get_matrix_payload()

    def export_holley_tsv(self, include_learn: bool = True) -> str:
        """Tab-delimited 16x16 recommended VE table, ready to paste into Holley's Fuel VE table."""
        return self.get_matrix_payload(include_learn=include_learn, include_comparison=False)["holley_tsv_ve"]

    def _snapshot(self) -> Dict[str, Any]:
        """Compact per-cell record of the current corrections, used as the 'before' side of a comparison."""
        payload = self.get_matrix_payload(include_learn=True, include_comparison=False)
        cells: Dict[str, Dict[str, float]] = {}
        for row in payload["rows"]:
            for c in row["cells"]:
                if c["hits"] > 0:
                    cells[f"{c['map_kpa']}:{c['rpm']}"] = {
                        "raw": c["raw_correction_pct"],
                        "hits": c["hits"],
                    }
        return {"source": self.last_source, "cells": cells}

    def _build_comparison(self, current_cells: Dict[str, Dict[str, float]]) -> Optional[Dict[str, Any]]:
        """Compares this log's per-cell corrections to the previous log's (cells present in both)."""
        prev = self._prev_snapshot
        if not prev:
            return None
        shared = [k for k in current_cells if k in prev["cells"]]
        if not shared:
            return {
                "previous_source": prev["source"],
                "current_source": self.last_source,
                "cells_compared": 0,
                "trend": "no_overlap",
                "summary": "The previous and current logs share no VE cells, so they can't be compared.",
            }
        prev_abs = sum(abs(prev["cells"][k]["raw"]) for k in shared) / len(shared)
        now_abs = sum(abs(current_cells[k]["raw"]) for k in shared) / len(shared)
        improved = sum(1 for k in shared if abs(current_cells[k]["raw"]) < abs(prev["cells"][k]["raw"]) - 0.5)
        worsened = sum(1 for k in shared if abs(current_cells[k]["raw"]) > abs(prev["cells"][k]["raw"]) + 0.5)
        delta = now_abs - prev_abs
        if delta < -0.3:
            trend = "improving"
        elif delta > 0.3:
            trend = "worse"
        else:
            trend = "flat"
        return {
            "previous_source": prev["source"],
            "current_source": self.last_source,
            "cells_compared": len(shared),
            "mean_abs_correction_prev_pct": round(prev_abs, 2),
            "mean_abs_correction_now_pct": round(now_abs, 2),
            "cells_improved": improved,
            "cells_worsened": worsened,
            "trend": trend,
            "summary": (
                f"{len(shared)} cells in common: average error {prev_abs:.1f}% -> {now_abs:.1f}% "
                f"({improved} improved, {worsened} worse)."
            ),
        }

    def get_matrix_payload(self, include_learn: bool = True, include_comparison: bool = True) -> Dict[str, Any]:
        """
        Returns the full 16x16 matrix (ordered top-to-bottom from highest MAP 260 kPa
        down to 20 kPa, matching Holley Terminator X V3's visual Fuel VE table layout)
        using the Fairmont VE Optimizer multiplicative transfer function:
          - If include_learn=True (Fold Learn Table + CL Comp into Base VE; reset Learn after pasting):
              M_total = (1 + Learn/100) * (1 + CL_Comp/100) * (1 + Residual_AFR_Err) - 1
          - If include_learn=False (Apply only active CL Comp / Residual AFR Err; keep existing Learn Table):
              M_total = (1 + CL_Comp/100) * (1 + Residual_AFR_Err) - 1
        targeting steady-state closed-loop trim error within ±2.0%.
        """
        rows_out: List[Dict[str, Any]] = []
        cells_touched = 0
        cells_needing_change = 0
        fp_warning_cells = 0
        knock_cells = 0
        cells_with_active_learn = 0
        low_confidence_cells = 0
        limited_cells = 0
        snapshot_cells: Dict[str, Dict[str, float]] = {}
        tsv_ve_lines: List[str] = []
        tsv_corr_lines: List[str] = []

        for m_idx in range(15, -1, -1):
            map_val = self.map_axis[m_idx]
            row_cells: List[Dict[str, Any]] = []
            ve_line_vals: List[str] = []
            corr_line_vals: List[str] = []

            for r_idx, rpm_val in enumerate(self.rpm_axis):
                acc = self.grid[m_idx][r_idx]
                default_ve = self.default_base_ve[m_idx][r_idx]

                if acc.hits == 0:
                    row_cells.append({
                        "rpm": rpm_val,
                        "map_kpa": map_val,
                        "hits": 0,
                        "base_ve": default_ve,
                        "recommended_ve": default_ve,
                        "correction_pct": 0.0,
                        "raw_correction_pct": 0.0,
                        "confidence": "none",
                        "limited": False,
                        "cl_comp_pct": 0.0,
                        "learn_pct": 0.0,
                        "afr_avg": None,
                        "target_afr": None,
                        "fp_warning": False,
                        "knock_deg": 0.0,
                    })
                    ve_line_vals.append(f"{default_ve:.1f}")
                    corr_line_vals.append("0.0")
                    continue

                cells_touched += 1
                avg_afr = acc.sum_afr / acc.hits
                avg_target = acc.sum_target_afr / acc.hits
                avg_cl = acc.sum_cl_comp / acc.hits
                avg_learn = acc.sum_learn / acc.hits
                avg_base_ve = acc.sum_base_ve / acc.hits
                avg_fp = acc.sum_fuel_psi / acc.hits
                avg_diff_fp = acc.sum_diff_fuel_psi / acc.hits
                avg_knock = acc.sum_knock / acc.hits
                expected_rail_psi = self.base_fuel_psi + ((map_val - 101.325) * 0.145038)

                if abs(avg_learn) >= 0.5:
                    cells_with_active_learn += 1

                # Multiplicative ECU Fuel Trim + Residual Wideband Error:
                # Delivered_Fuel = Base_VE * (1 + Learn/100) * (1 + CL_Comp/100)
                afr_err_ratio = (avg_afr - avg_target) / max(avg_target, 8.0)
                learn_mult = (1.0 + (avg_learn / 100.0)) if include_learn else 1.0
                cl_mult = 1.0 + (avg_cl / 100.0)

                # When Closed Loop is active (|avg_cl| > 0.05), CL_Comp already reflects most of the instant error,
                # plus any uncompensated residual AFR error if CL_Comp is clamped or still converging.
                if abs(avg_cl) > 0.05 or (include_learn and abs(avg_learn) > 0.05):
                    res_mult = (1.0 + 0.5 * afr_err_ratio) if abs(afr_err_ratio) > 0.01 else 1.0
                    total_mult = (learn_mult * cl_mult * res_mult) - 1.0
                else:
                    # Open-loop or zero CL/Learn: use direct wideband AFR error ratio
                    total_mult = (learn_mult * (1.0 + afr_err_ratio)) - 1.0

                cl_comp_percent = total_mult * 100.0

                # Clamp the raw single-pass correction to +/-20% as an absolute sanity bound
                raw_corr_pct = max(-20.0, min(20.0, cl_comp_percent))

                fp_warn = acc.fuel_psi_drop_hits > (acc.hits * 0.25)
                if fp_warn:
                    fp_warning_cells += 1
                    # Never add positive VE fuel if mechanical rail pressure dropped below 58 PSI + 1:1 boost!
                    if raw_corr_pct > 0:
                        raw_corr_pct = 0.0

                if avg_knock >= 1.5:
                    knock_cells += 1

                # Confidence from steady-state sample count; thin cells are never changed.
                if acc.hits < self.min_hits:
                    confidence = "low"
                    low_confidence_cells += 1
                    clamped_corr_pct = 0.0
                    limited = False
                else:
                    confidence = "medium" if acc.hits < self.min_hits * 3 else "high"
                    # Per-pass limiter: move the table gradually, not all at once from one pull.
                    clamped_corr_pct = max(-self.max_step_pct, min(self.max_step_pct, raw_corr_pct))
                    limited = abs(raw_corr_pct) > self.max_step_pct + 1e-9
                    if limited:
                        limited_cells += 1

                snapshot_cells[f"{map_val}:{rpm_val}"] = {"raw": raw_corr_pct, "hits": acc.hits}

                # Target steady-state closed-loop trim error within ±2.0%
                if abs(clamped_corr_pct) > self.steady_trim_target_pct:
                    cells_needing_change += 1

                # Exact Spec Formula: New_VE = Current_VE * (1.0 + (CL_Comp_Percent / 100.0))
                rec_ve = round(avg_base_ve * (1.0 + (clamped_corr_pct / 100.0)), 1)
                rec_ve = max(15.0, min(160.0, rec_ve))

                row_cells.append({
                    "rpm": rpm_val,
                    "map_kpa": map_val,
                    "hits": acc.hits,
                    "base_ve": round(avg_base_ve, 1),
                    "recommended_ve": rec_ve,
                    "correction_pct": round(clamped_corr_pct, 1),
                    "raw_correction_pct": round(raw_corr_pct, 1),
                    "confidence": confidence,
                    "limited": limited,
                    "cl_comp_pct": round(avg_cl, 1),
                    "learn_pct": round(avg_learn, 1),
                    "afr_avg": round(avg_afr, 2),
                    "target_afr": round(avg_target, 2),
                    "fuel_psi": round(avg_fp, 1),
                    "expected_rail_psi": round(expected_rail_psi, 1),
                    "diff_fuel_psi": round(avg_diff_fp, 1),
                    "fp_warning": fp_warn,
                    "knock_deg": round(avg_knock, 1),
                })
                ve_line_vals.append(f"{rec_ve:.1f}")
                corr_line_vals.append(f"{clamped_corr_pct:+.1f}")

            rows_out.append({
                "map_kpa": map_val,
                "boost_psig": round(max(0.0, (map_val - 101.3) * 0.145038), 1),
                "cells": row_cells,
            })
            tsv_ve_lines.append("\t".join(ve_line_vals))
            tsv_corr_lines.append("\t".join(corr_line_vals))

        return {
            "platform": FAIRMONT_PLATFORM_SPEC["vehicle"],
            "engine": FAIRMONT_PLATFORM_SPEC["engine"],
            "source": self.last_source,
            "last_source": self.last_source,
            "max_step_pct": self.max_step_pct,
            "min_hits": self.min_hits,
            "low_confidence_cells": low_confidence_cells,
            "limited_cells": limited_cells,
            "cells_populated": cells_touched,
            "comparison": self._build_comparison(snapshot_cells) if include_comparison else None,
            "tune_history": self.get_history(),
            "include_learn": include_learn,
            "cells_with_active_learn": cells_with_active_learn,
            "learn_action_notice": (
                "Fuel Learn % is INCLUDED in these VE values. After pasting into Base Fuel VE, click 'Reset Learn Table' in Terminator X.exe so the ECU does not double-apply Learn!"
                if include_learn
                else "Fuel Learn % is EXCLUDED (only Closed-Loop Comp & Wideband AFR error applied). Leave your ECU Fuel Learn table as-is, or use this after clicking 'Transfer Learn to Base'."
            ),
            "base_fuel_psi": self.base_fuel_psi,
            "min_coolant_f": self.min_coolant_f,
            "steady_trim_target_pct": self.steady_trim_target_pct,
            "total_samples": self.total_samples_ingested,
            "filtered_samples": self.filtered_samples,
            "filter_breakdown": {
                "transient_roc_rejected": self.transient_rejected_samples,
                "dfco_rejected": self.dfco_rejected_samples,
                "cold_engine_rejected": self.cold_rejected_samples,
                "enrichment_modifier_rejected": self.enrichment_rejected_samples,
                "sloppy_transbrake_staging_rejected": self.staging_rejected_samples,
            },
            "cells_touched": cells_touched,
            "cells_needing_change": cells_needing_change,
            "fp_warning_cells": fp_warning_cells,
            "knock_cells": knock_cells,
            "rpm_axis": self.rpm_axis,
            "map_axis_desc": list(reversed(self.map_axis)),
            "loaded_terx_path": self.loaded_terx_path,
            "loaded_terx_comment": self.loaded_terx_comment,
            "rows": rows_out,
            "holley_tsv_ve": "\r\n".join(tsv_ve_lines),
            "holley_tsv_correction_pct": "\r\n".join(tsv_corr_lines),
        }


_ALERT_RANK = {"info": 0, "warning": 1, "critical": 2}


def build_safety_alerts(card: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Derives explicit, worst-first safety alerts from a pull scorecard.

    Thresholds (Fairmont: 58 PSI boost-referenced rail, Deka 80s, VS 78/75):
      - AFR leaner than target by >= 0.5 under boost (critical at >= 0.8; whole-pull average)
      - Injector differential pressure < 55 PSI (critical < 52)
      - Knock retard >= 1.5 deg (critical >= 4.0)
      - Overboost / over-rev (critical)
      - Injector duty >= 85% (critical >= 92%)
    """
    alerts: List[Dict[str, str]] = []

    def add(level: str, code: str, message: str) -> None:
        alerts.append({"level": level, "code": code, "message": message})

    boost = float(card.get("peak_boost_psig", 0.0) or 0.0)
    afr_err = float(card.get("afr_error", 0.0) or 0.0)
    if boost >= 1.0 and afr_err >= 0.5:
        add(
            "critical" if afr_err >= 0.8 else "warning",
            "lean_under_boost",
            f"LEAN UNDER BOOST: AFR averaged {afr_err:+.2f} leaner than target at up to {boost:.1f} psi. "
            "Do not increase boost or timing until this is fixed.",
        )

    diff = card.get("min_differential_fuel_psi")
    if diff is not None and diff < 55.0:
        add(
            "critical" if diff < 52.0 else "warning",
            "fuel_pressure_low",
            f"FUEL PRESSURE: injector differential fell to {diff:.1f} psi (target 58). "
            "Check pump voltage/flow, filter and the regulator boost reference line before adding VE.",
        )

    knock = float(card.get("max_knock_retard_deg", 0.0) or 0.0)
    if knock >= 1.5:
        add(
            "critical" if knock >= 4.0 else "warning",
            "knock",
            f"KNOCK: retard reached {knock:.1f} degrees. Check fuel quality/ethanol %, IAT and plugs before pulling timing.",
        )

    if card.get("peak_boost_psig", 0.0) > card.get("boost_limit_psi", 17.0):
        add(
            "critical",
            "overboost",
            f"OVERBOOST: {boost:.1f} psi exceeds the {card.get('boost_limit_psi', 17.0):.0f} psi limit for this fuel.",
        )

    if card.get("peak_rpm", 0.0) > 6800.0:
        add("critical", "overrev", f"OVER-REV: {card.get('peak_rpm', 0.0):.0f} RPM exceeded the 6800 RPM limit.")

    duty = float(card.get("max_injector_duty_pct", 0.0) or 0.0)
    if duty >= 85.0:
        add(
            "critical" if duty >= 92.0 else "warning",
            "injector_duty",
            f"INJECTOR DUTY: Deka 80s reached {duty:.1f}% duty. Little headroom left for more boost.",
        )

    alerts.sort(key=lambda a: -_ALERT_RANK[a["level"]])
    return alerts


def worst_alert_level(alerts: List[Dict[str, str]]) -> str:
    return max((a["level"] for a in alerts), key=lambda lv: _ALERT_RANK[lv], default="info")


def compare_scorecards(current: Dict[str, Any], previous: Dict[str, Any]) -> Dict[str, Any]:
    """Pull-to-pull deltas (current minus previous) for the headline numbers."""
    def delta(key: str) -> Optional[float]:
        a, b = current.get(key), previous.get(key)
        if a is None or b is None:
            return None
        return round(float(a) - float(b), 2)

    def _afr_trend() -> Optional[bool]:
        if "afr_error" not in current or "afr_error" not in previous:
            return None
        a, b = abs(current["afr_error"]), abs(previous["afr_error"])
        if a < b - 0.02:
            return True
        if a > b + 0.02:
            return False
        return None  # effectively unchanged

    return {
        "previous_log": previous.get("log_name"),
        "current_log": current.get("log_name"),
        "peak_boost_psig": delta("peak_boost_psig"),
        "peak_rpm": delta("peak_rpm"),
        "afr_error": delta("afr_error"),
        "min_differential_fuel_psi": delta("min_differential_fuel_psi"),
        "max_knock_retard_deg": delta("max_knock_retard_deg"),
        "max_injector_duty_pct": delta("max_injector_duty_pct"),
        "afr_error_improved": _afr_trend(),
    }


class PostPullDetector:
    """
    Automatically detects when a WOT pull starts and finishes on the 1980 Ford Fairmont,
    auditing:
      - Peak RPM (vs 6800 RPM hard limit)
      - Boost PSI (12-15 PSI standard, >17 PSI pump/blend cut, 20 PSI max E85)
      - 58 PSI base + 1:1 boost-referenced fuel rail pressure (Racetronix 420 LPH + Deka 80 lb/hr)
      - 4L80E Gear progression, Yank 3600 RPM converter slip %, and 3rd-gear Sloppy Transbrake staging
    """

    def __init__(self, base_fuel_psi: float = 58.0):
        self.base_fuel_psi = base_fuel_psi
        self._in_pull = False
        self._pull_start_ts = 0.0
        self._pull_samples: List[Dict[str, float]] = []
        self.recent_scorecards: List[Dict[str, Any]] = []

    def on_snapshot(self, snap: Dict[str, float]) -> Optional[Dict[str, Any]]:
        tps = snap.get("tps", 0.0)
        rpm = snap.get("rpm", 0.0)
        now = time.time()

        if not self._in_pull:
            if tps >= 75.0 and rpm >= 2200.0:
                self._in_pull = True
                self._pull_start_ts = now
                self._pull_samples = [dict(snap)]
            return None

        if tps >= 65.0:
            self._pull_samples.append(dict(snap))
            return None

        self._in_pull = False
        if len(self._pull_samples) < 4:
            self._pull_samples.clear()
            return None

        card = self.build_scorecard(self._pull_samples, duration_s=max(0.5, now - self._pull_start_ts))
        self._pull_samples.clear()
        self.recent_scorecards.insert(0, card)
        del self.recent_scorecards[10:]
        return card

    def build_scorecard(self, samples: List[Dict[str, float]], duration_s: float = 0.0) -> Dict[str, Any]:
        peak_rpm = max(s.get("rpm", 0.0) for s in samples)
        peak_map = max(s.get("map_kpa", 100.0) for s in samples)
        baro = samples[0].get("baro_kpa", 101.325) or 101.325
        peak_boost = max(0.0, (peak_map - baro) * 0.145038)

        avg_afr = sum(s.get("afr_avg") or s.get("afr_left") or 12.5 for s in samples) / len(samples)
        avg_target = sum(s.get("target_afr", 12.5) for s in samples) / len(samples)
        afr_error = avg_afr - avg_target

        avg_cl = sum(s.get("closed_loop_comp", 0.0) for s in samples) / len(samples)
        avg_learn = sum(s.get("current_learn", 0.0) for s in samples) / len(samples)
        max_duty = max(s.get("injector_duty", 0.0) for s in samples)
        max_knock = max(s.get("knock_retard", 0.0) for s in samples)
        ethanol_pct = max((s.get("ethanol_pct", 0.0) for s in samples), default=0.0)

        # Evaluate 1:1 boost-referenced fuel pressure sample-by-sample across the pull:
        # At every instant t, Expected_Rail_PSIG(t) = 58.0 + Manifold_PSIG(t),
        # so Differential Injector Pressure dP_inj(t) = Rail_PSIG(t) - Manifold_PSIG(t) = 58.0 PSI.
        fp_evals = []
        for s in samples:
            s_map = s.get("map_kpa", 101.325)
            s_baro = s.get("baro_kpa", baro) or baro
            s_man_psi = (s_map - s_baro) * 0.145038
            raw_fp = s.get("fuel_pressure")
            s_fp = float(raw_fp) if (raw_fp is not None and raw_fp > 0.0) else (self.base_fuel_psi + s_man_psi)
            m = compute_manifold_referenced_fuel_metrics(
                fuel_psi_gauge=s_fp,
                map_kpa=s_map,
                baro_kpa=s_baro,
                base_fuel_psi=self.base_fuel_psi,
            )
            fp_evals.append((s_map, s_fp, float(m["differential_psi"]), bool(m["fp_drop"])))

        min_diff_fp = min(x[2] for x in fp_evals)
        # Find rail pressure at peak MAP sample
        peak_map_eval = max(fp_evals, key=lambda x: x[0])
        fp_at_peak_boost = peak_map_eval[1]
        min_fp = min(x[1] for x in fp_evals)

        # 4L80E & Yank 3600 Converter & Sloppy Transbrake metrics
        staging_rows = [s for s in samples if is_sloppy_transbrake_staging(s)]
        high_rpm_rows = [s for s in samples if s.get("rpm", 0.0) >= 4800.0 and s.get("vehicle_speed", 0.0) > 25.0]
        if high_rpm_rows:
            conv_metrics = [compute_4l80e_converter_metrics(s) for s in high_rpm_rows]
            avg_slip_pct = sum(m["converter_slip_pct"] for m in conv_metrics) / len(conv_metrics)
            peak_mph = max(s.get("vehicle_speed", 0.0) for s in samples)
            top_gear = max(int(round(s.get("trans_gear", 3))) for s in high_rpm_rows)
        else:
            avg_slip_pct = 0.0
            peak_mph = max((s.get("vehicle_speed", 0.0) for s in samples), default=0.0)
            top_gear = max((int(round(s.get("trans_gear", 0))) for s in samples), default=0)

        expected_fp = self.base_fuel_psi + peak_boost
        # True 1:1 boost-referenced check: injector differential pressure (Rail - Boost) must stay >= 52.0 PSI (within 6 PSI of 58 PSI base)
        fp_ok = not any(x[3] for x in fp_evals)

        # Evaluate Fairmont Boost Safety Rules (17.0 PSI low-E cut / 20.0 PSI max E85)
        boost_limit_psi = 20.0 if ethanol_pct >= 65.0 else 17.0
        overboost = peak_boost > boost_limit_psi
        overrev = peak_rpm > 6800.0

        verdict_parts: List[str] = [
            f"Fairmont pull to {int(round(peak_rpm))} RPM"
            + (f" at {peak_boost:.1f} psi boost" if peak_boost >= 1.0 else f" ({peak_map:.0f} kPa MAP)")
            + (f" ({peak_mph:.0f} mph, 4L80E Gear {top_gear})." if peak_mph > 5.0 else ".")
        ]
        severity = "info"

        if staging_rows:
            stg_rpm = sum(s.get("rpm", 0.0) for s in staging_rows) / len(staging_rows)
            stg_timing = min(s.get("ignition_timing", 5.0) for s in staging_rows)
            verdict_parts.append(
                f"3rd-Gear Sloppy Transbrake staged cleanly at {stg_rpm:.0f} RPM ({stg_timing:.1f}° BTDC)."
            )

        if overboost:
            severity = "critical"
            verdict_parts.append(
                f"OVERBOOST ALERT: {peak_boost:.1f} psi exceeds {boost_limit_psi:.0f} psi Fairmont safety limit!"
            )
        if overrev:
            severity = "critical"
            verdict_parts.append(f"OVER-REV: {peak_rpm:.0f} RPM exceeded 6800 RPM limit!")
        if not fp_ok:
            severity = "critical"
            verdict_parts.append(
                f"WARNING: 1:1 boost-referenced differential fuel pressure sagged to {min_diff_fp:.1f} psi (Rail {fp_at_peak_boost:.1f} vs {expected_fp:.1f} psi expected @ peak boost). Do NOT add VE!"
            )
        if max_duty >= 85.0:
            severity = "warning" if severity != "critical" else "critical"
            verdict_parts.append(f"Deka 80 lb/hr injectors reached {max_duty:.1f}% duty cycle.")
        if max_knock >= 1.5:
            severity = "warning" if severity != "critical" else "critical"
            verdict_parts.append(f"Knock retard reached {max_knock:.1f}°—pull 2° timing in peak torque cells.")
        if abs(avg_cl) > 2.0 or abs(avg_learn) > 2.0 or abs(afr_error) >= 0.4:
            if severity == "info":
                severity = "warning"
            direction = "rich" if (avg_cl + avg_learn < -2.0 or afr_error < -0.3) else "lean"
            verdict_parts.append(
                f"WOT fueling is {direction} (AFR {avg_afr:.2f} vs {avg_target:.2f}, CL/Learn {avg_cl + avg_learn:+.1f}%). Click Copy 16x16 VE Table."
            )
        else:
            verdict_parts.append(f"WOT AFR tracked {avg_afr:.2f} (Target {avg_target:.2f}) within ±2% steady target.")

        step = max(1, len(samples) // 60)
        t0 = samples[0].get("timestamp_s", 0.0) or samples[0].get("timestamp", 0.0)
        trace: List[Dict[str, Any]] = []
        for i in range(0, len(samples), step):
            s_row = samples[i]
            cur_t = s_row.get("timestamp_s", 0.0) or s_row.get("timestamp", 0.0)
            s_map = s_row.get("map_kpa", 101.325)
            s_boost = max(0.0, (s_map - baro) * 0.145038)
            s_afr = s_row.get("afr_avg") or s_row.get("afr_left") or 12.5
            s_tafr = s_row.get("target_afr", 12.5)
            raw_fp = s_row.get("fuel_pressure")
            s_man_psi = (s_map - baro) * 0.145038
            s_fp = float(raw_fp) if (raw_fp is not None and raw_fp > 0.0) else (self.base_fuel_psi + s_man_psi)
            s_diff_fp = s_fp - s_man_psi
            trace.append({
                "t": round(max(0.0, cur_t - t0), 2),
                "rpm": round(s_row.get("rpm", 0.0)),
                "boost": round(s_boost, 1),
                "afr": round(s_afr, 2),
                "target_afr": round(s_tafr, 2),
                "diff_fp": round(s_diff_fp, 1),
                "knock": round(s_row.get("knock_retard", 0.0), 1),
            })

        card = {
            "timestamp": time.time(),
            "duration_s": round(duration_s, 1),
            "trace": trace,
            "peak_rpm": round(peak_rpm, 0),
            "peak_map_kpa": round(peak_map, 1),
            "peak_boost_psig": round(peak_boost, 1),
            "boost_limit_psi": boost_limit_psi,
            "ethanol_pct": round(ethanol_pct, 1),
            "avg_afr": round(avg_afr, 2),
            "target_afr": round(avg_target, 2),
            "afr_error": round(afr_error, 2),
            "avg_cl_comp_pct": round(avg_cl, 1),
            "avg_learn_pct": round(avg_learn, 1),
            "min_fuel_pressure_psi": round(min_fp, 1),
            "fp_at_peak_boost_psi": round(fp_at_peak_boost, 1),
            "min_differential_fuel_psi": round(min_diff_fp, 1),
            "expected_fuel_pressure_psi": round(expected_fp, 1),
            "fuel_pressure_ok": fp_ok,
            "max_injector_duty_pct": round(max_duty, 1),
            "max_knock_retard_deg": round(max_knock, 1),
            "top_gear_4l80e": top_gear,
            "peak_mph": round(peak_mph, 1),
            "yank_3600_avg_slip_pct": round(avg_slip_pct, 1),
            "sloppy_transbrake_samples": len(staging_rows),
            "severity": severity,
            "verdict": " ".join(verdict_parts),
        }
        alerts = build_safety_alerts(card)
        card["safety_alerts"] = alerts
        card["safety_level"] = worst_alert_level(alerts)
        return card

class AutoHandoffWatcher:
    """
    Zero-touch background coordinator that:
      1. Monitors Terminator X.exe WinUSB lock state (yielding or reclaiming the cable).
      2. Watches Documents/Holley/Terminator X V3/Data Logs for new or updated .dl/.dlz files,
         auto-ingesting them into the 16x16 Fairmont VE Optimizer and Post-Pull Scorecard engine.
    """

    def __init__(
        self,
        listener: Any,
        ve_optimizer: VETableOptimizer,
        pull_detector: PostPullDetector,
        on_event_callback: Optional[Callable[[Dict[str, Any]], Coroutine]] = None,
    ):
        self.listener = listener
        self.ve_optimizer = ve_optimizer
        self.pull_detector = pull_detector
        self.on_event_callback = on_event_callback
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._seen_mtimes: Dict[str, float] = {}
        # Files are only parsed once their size and mtime stop changing between polls, so a log
        # that Holley software is still writing is never read half-finished.
        self._last_stat: Dict[str, tuple] = {}
        self._fail_counts: Dict[str, int] = {}
        self.max_ingest_retries = 3
        self.handoff_mode: str = "initializing"
        self.last_auto_ingested_log: Optional[str] = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        files = discover_local_holley_files()
        for dl in files.get("datalogs", []):
            self._seen_mtimes[dl["path"]] = dl["modified"]
        # Tunes already on disk at startup are baseline, not "new" - only later saves trigger an audit.
        for tune in files.get("tunes", []):
            self._seen_mtimes[tune["path"]] = tune["modified"]

        if files.get("datalogs") and self.ve_optimizer.total_samples_ingested == 0:
            latest = files["datalogs"][0]
            try:
                self._ingest_file(latest["path"])
            except Exception as e:
                logger.debug("Initial datalog preload skipped: %s", e)

        self._task = asyncio.create_task(self._watch_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def _ingest_file(self, path: str) -> Dict[str, Any]:
        parser = HolleyDatalogParser(path)
        rows = parser.parse_rows()
        self.ve_optimizer.ingest_datalog(path)

        wot_rows = [r for r in rows if r.get("tps", 0.0) >= 75.0]
        scorecard = None
        if wot_rows:
            dur = wot_rows[-1].get("timestamp_s", 0.0) - wot_rows[0].get("timestamp_s", 0.0)
            scorecard = self.pull_detector.build_scorecard(wot_rows, duration_s=max(1.0, dur))
            scorecard["log_name"] = Path(path).name
            # Re-saving the same log replaces its scorecard instead of stacking duplicates.
            self.pull_detector.recent_scorecards[:] = [
                s for s in self.pull_detector.recent_scorecards if s.get("log_name") != scorecard["log_name"]
            ]
            self.pull_detector.recent_scorecards.insert(0, scorecard)
            del self.pull_detector.recent_scorecards[10:]

        self.last_auto_ingested_log = Path(path).name
        return {
            "log_name": Path(path).name,
            "path": path,
            "rows": len(rows),
            "scorecard": scorecard,
        }

    def _is_stable(self, path: str) -> bool:
        """True when the file's size/mtime are unchanged since the previous poll (write finished)."""
        try:
            st = Path(path).stat()
        except OSError:
            return False
        sig = (st.st_size, st.st_mtime)
        stable = self._last_stat.get(path) == sig and st.st_size > 0
        self._last_stat[path] = sig
        return stable

    async def _watch_loop(self) -> None:
        while self._running:
            try:
                from app.hardware.detection import check_holley_software_lock
                lock_info = check_holley_software_lock()
                if lock_info.get("locked"):
                    self.handoff_mode = "watching_holley_datalog_folder (Terminator X.exe active)"
                elif getattr(self.listener, "_running", False):
                    self.handoff_mode = f"live_can_streaming ({getattr(self.listener, 'interface', 'can0')})"
                else:
                    self.handoff_mode = "standby_auto_watch"

                files = discover_local_holley_files()

                # 1. Watch Datalogs (.dl / .dlz)
                for dl in files.get("datalogs", []):
                    p = dl["path"]
                    mtime = dl["modified"]
                    prev_mtime = self._seen_mtimes.get(p)
                    if prev_mtime is None or mtime > prev_mtime + 0.5:
                        if not self._is_stable(p):
                            continue  # still being written; look again next poll
                        try:
                            result = self._ingest_file(p)
                            parser = HolleyDatalogParser(p)
                        except Exception as e:
                            n = self._fail_counts.get(p, 0) + 1
                            self._fail_counts[p] = n
                            logger.warning("Datalog %s not readable yet (attempt %d): %s", dl["name"], n, e)
                            if n >= self.max_ingest_retries:
                                self._seen_mtimes[p] = mtime  # give up on this version of the file
                            continue
                        self._fail_counts.pop(p, None)
                        self._seen_mtimes[p] = mtime
                        logger.info("Auto-ingested Holley datalog: %s", dl["name"])
                        if hasattr(self.listener, "inject_decoded_frames"):
                            await self.listener.inject_decoded_frames(parser.to_decoded_frames())
                        if self.on_event_callback:
                            await self.on_event_callback({
                                "type": "datalog_auto_ingested",
                                **result,
                            })

                # 2. Watch Calibration / Tune Files (.terx / .hefi / .gcfgx)
                for tune in files.get("tunes", []):
                    p = tune["path"]
                    mtime = tune["modified"]
                    prev_mtime = self._seen_mtimes.get(p)
                    if prev_mtime is None or mtime > prev_mtime + 0.5:
                        if not self._is_stable(p):
                            continue
                        self._seen_mtimes[p] = mtime
                        logger.info("Auto-detected Holley tune file: %s", tune["name"])
                        if self.on_event_callback:
                            await self.on_event_callback({
                                "type": "tune_auto_detected",
                                "tune_name": tune["name"],
                                "path": p,
                                "size_bytes": tune.get("size_bytes", 0),
                            })

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("AutoHandoffWatcher tick error: %s", e)

            await asyncio.sleep(1.5)
