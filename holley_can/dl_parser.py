"""
dl_parser.py — Native Holley .DL / .DLZ Binary Datalog Decompressor & Analyzer

Integrates the reverse-engineered binary parsers from `holley-efi-parser` directly
into `holley-can-agent` with zero external C-extension dependencies (pure Python `struct`),
supporting:
  1. .DLZ RLE + 4-byte endian swap decompression (100% lossless to .DL)
  2. Terminator X V3 (`0x0095365F`, 'TSLCD 3.5 Logfile Terminator X', 2512 bytes/row @ offset 12012)
  3. Holley V6 (`0x0085F41F`, 4120 bytes/row @ offset 16456)
  4. Automatic discovery of local `.dl`, `.dlz`, and `.terx` files in Documents/Holley
"""

from __future__ import annotations

import os
import struct
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .protocol import CHANNEL_BY_NAME, DecodedFrame


# ─── DLZ Decompressor (Ported from holley-efi-parser/dlz_decompressor.py) ────

def _byte_swap_4(data: bytes) -> bytes:
    """Swap bytes in each 4-byte group: [A,B,C,D] -> [D,C,B,A]."""
    result = bytearray()
    for i in range(0, len(data), 4):
        chunk = data[i:i + 4]
        if len(chunk) == 4:
            result.extend((chunk[3], chunk[2], chunk[1], chunk[0]))
        else:
            result.extend(chunk)
    return bytes(result)


def _rle_decompress(data: bytes) -> bytes:
    """RLE decompression matching Holley EFI software (0xFF COUNT VALUE)."""
    result = bytearray()
    i = 0
    length = len(data)
    while i < length:
        byte = data[i]
        i += 1
        if byte == 0xFF:
            if i + 1 >= length:
                result.append(byte)
                break
            count = data[i]
            value = data[i + 1]
            i += 2
            if count == 0:
                result.append(0xFF)
            else:
                result.extend([value] * count)
        else:
            result.append(byte)
    return bytes(result)


def decompress_dlz(dlz_data: bytes) -> bytes:
    """Decompress Holley .DLZ bytes into raw .DL binary bytes."""
    swapped = _byte_swap_4(dlz_data)
    decompressed = _rle_decompress(swapped)
    return _byte_swap_4(decompressed)


# ─── Verified Terminator X V3 .DL Channel Slot Map (2512-byte rows) ─────────
# Empirically verified against Terminator X V3 'sample data log.dl':
# Each 2512-byte row contains 314 8-byte slots (slot 0 = 64-bit timestamp header,
# slots 1..313 = <fI float32 value + uint32 status).

V3_SLOT_TO_CHANNEL: dict[int, str] = {
    1: "rpm",
    2: "fuel_pw",
    3: "injector_duty",
    4: "closed_loop_comp",
    5: "target_afr",
    6: "afr_left",
    7: "afr_avg",
    8: "afr_right",
    9: "air_temp_enrich",
    10: "coolant_enrich",
    11: "coolant_afr_offset",
    12: "afterstart_enrich",
    13: "current_learn",
    14: "closed_loop",
    15: "learn_status",
    16: "fuel_economy",
    17: "fuel_flow",
    18: "map_roc",
    19: "tps_roc",
    20: "tuning_change",
    21: "estimated_ve",
    25: "ignition_timing",
    26: "knock_retard",
    29: "iac_position",
    30: "idle_speed",
    31: "map_kpa",
    32: "tps",
    33: "iat",
    34: "coolant_temp",
    35: "baro_kpa",
    36: "battery_voltage",
    37: "oil_pressure",
    38: "fuel_pressure",
    39: "pedal_position",
    40: "rev_limit_main",
    41: "rev_limit_1",
    45: "lockup_status",
    48: "base_fuel_lb",
    49: "base_fuel_ve",
    50: "spark_advance",
    51: "base_target_afr",
    52: "base_ign_dwell",
    145: "trans_gear",
    146: "vehicle_speed",
    147: "line_pressure",
    148: "input_speed",
    150: "tcc_status",
    151: "trans_temp",
}

# V6 interleaved slot map (matches official DBC channel indices 1..225)
V6_SLOT_TO_CHANNEL: dict[int, str] = {
    2: "rpm",
    3: "fuel_pw",
    4: "injector_duty",
    5: "closed_loop_comp",
    6: "target_afr",
    7: "afr_left",
    8: "afr_right",
    9: "afr_avg",
    14: "current_learn",
    15: "closed_loop",
    18: "fuel_flow",
    22: "estimated_ve",
    23: "ignition_timing",
    24: "knock_retard",
    27: "iac_position",
    28: "idle_speed",
    29: "map_kpa",
    30: "tps",
    31: "iat",
    32: "coolant_temp",
    33: "baro_kpa",
    34: "battery_voltage",
    35: "oil_pressure",
    36: "fuel_pressure",
    37: "pedal_position",
    220: "trans_gear",
    221: "vehicle_speed",
    222: "line_pressure",
    223: "input_speed",
    225: "tcc_status",
    226: "trans_temp",
}


class HolleyDatalogParser:
    """
    Universal parser for Holley .DL and .DLZ binary datalogs (Terminator X V3 & Holley V6).
    """

    MAGIC_V3 = 0x0095365F
    MAGIC_V5_V6 = 0x0085F41F

    V3_DATA_START = 12012
    V3_BYTES_PER_ROW = 2512  # 314 slots * 8 bytes

    V6_DATA_START = 16456
    V6_BYTES_PER_ROW = 4120  # 1030 floats * 4 bytes

    def __init__(self, file_path: str | Path):
        self.file_path = Path(file_path)
        raw = self.file_path.read_bytes()
        if self.file_path.suffix.lower() == ".dlz":
            self.dl_data = decompress_dlz(raw)
            self.was_compressed = True
        else:
            self.dl_data = raw
            self.was_compressed = False

        self.format_info = self._detect_format()
        if not self.format_info:
            raise ValueError(f"Unsupported or corrupt Holley datalog: {self.file_path.name}")

    def _detect_format(self) -> Optional[Dict[str, Any]]:
        if len(self.dl_data) < 64:
            return None

        magic, _, field_08, _ = struct.unpack("<4I", self.dl_data[:16])

        # Extract embedded header tune/cal name if present
        embedded_tune = ""
        try:
            header_slice = self.dl_data[780:860]
            ascii_chars = "".join(chr(b) if 32 <= b < 127 else " " for b in header_slice)
            for token in ascii_chars.split():
                if token.lower().endswith((".terx", ".hefi", ".tsc")):
                    embedded_tune = token
                    break
        except Exception:
            pass

        if magic == self.MAGIC_V3:
            # Primary V3 layout: 2512 bytes/row starting at 12012
            if len(self.dl_data) > self.V3_DATA_START:
                data_size = len(self.dl_data) - self.V3_DATA_START
                if data_size % self.V3_BYTES_PER_ROW == 0:
                    return {
                        "version": "V3 (Terminator X)",
                        "version_field": field_08,
                        "magic": magic,
                        "data_start": self.V3_DATA_START,
                        "bytes_per_row": self.V3_BYTES_PER_ROW,
                        "num_rows": data_size // self.V3_BYTES_PER_ROW,
                        "embedded_tune": embedded_tune,
                        "layout": "v3_2512",
                    }
            # Fallback V3 scan for 2064-byte (516 float) or 2512-byte rows
            for row_bytes in (2512, 2064):
                for ds in range(1000, min(16000, len(self.dl_data)), 4):
                    rem = (len(self.dl_data) - ds) % row_bytes
                    if rem == 0 and (len(self.dl_data) - ds) // row_bytes > 0:
                        return {
                            "version": "V3 (Terminator X)",
                            "version_field": field_08,
                            "magic": magic,
                            "data_start": ds,
                            "bytes_per_row": row_bytes,
                            "num_rows": (len(self.dl_data) - ds) // row_bytes,
                            "embedded_tune": embedded_tune,
                            "layout": "v3_2512" if row_bytes == 2512 else "v3_2064",
                        }

        elif magic == self.MAGIC_V5_V6:
            if field_08 == 5:
                raise ValueError(
                    "Holley V5 sparse .dl format detected; open once in Holley V6 to convert."
                )
            if len(self.dl_data) > self.V6_DATA_START:
                data_size = len(self.dl_data) - self.V6_DATA_START
                num_rows = data_size // self.V6_BYTES_PER_ROW
                if num_rows > 0:
                    return {
                        "version": f"V{field_08} (Holley EFI)",
                        "version_field": field_08,
                        "magic": magic,
                        "data_start": self.V6_DATA_START,
                        "bytes_per_row": self.V6_BYTES_PER_ROW,
                        "num_rows": num_rows,
                        "embedded_tune": embedded_tune,
                        "layout": "v6_4120",
                    }

        return None

    def parse_rows(self, max_rows: Optional[int] = None) -> List[Dict[str, float]]:
        """
        Parse rows into normalized channel dicts:
        [{"timestamp_s": 0.0, "rpm": 719.8, "map_kpa": 43.9, ...}, ...]
        """
        info = self.format_info
        ds = info["data_start"]
        bpr = info["bytes_per_row"]
        total_rows = info["num_rows"]
        layout = info["layout"]

        step = 1
        if max_rows and total_rows > max_rows:
            step = max(1, total_rows // max_rows)

        slot_map = V3_SLOT_TO_CHANNEL if layout.startswith("v3") else V6_SLOT_TO_CHANNEL
        rows: List[Dict[str, float]] = []
        t0_ms: Optional[int] = None

        for r in range(0, total_rows, step):
            row_off = ds + r * bpr
            if row_off + bpr > len(self.dl_data):
                break

            row_dict: Dict[str, float] = {"row_index": float(r)}
            if layout == "v3_2512":
                pt_ms = struct.unpack_from("<I", self.dl_data, row_off)[0]
                if t0_ms is None:
                    t0_ms = pt_ms
                row_dict["timestamp_s"] = round((pt_ms - t0_ms) / 1000.0, 3)

                for slot_idx, ch_name in slot_map.items():
                    byte_pos = row_off + slot_idx * 8
                    if byte_pos + 4 <= row_off + bpr:
                        val = struct.unpack_from("<f", self.dl_data, byte_pos)[0]
                        row_dict[ch_name] = round(float(val), 3)
            else:
                row_dict["timestamp_s"] = round(r * 0.02, 3)
                for slot_idx, ch_name in slot_map.items():
                    byte_pos = row_off + slot_idx * 8
                    if byte_pos + 4 <= row_off + bpr:
                        val = struct.unpack_from("<f", self.dl_data, byte_pos)[0]
                        row_dict[ch_name] = round(float(val), 3)

            # Compute derived boost_psig if map_kpa > baro_kpa
            map_kpa = row_dict.get("map_kpa", 0.0)
            baro_kpa = row_dict.get("baro_kpa", 101.325) or 101.325
            if map_kpa > baro_kpa:
                row_dict["boost_psig"] = round((map_kpa - baro_kpa) * 0.145038, 2)
            else:
                row_dict["boost_psig"] = 0.0

            rows.append(row_dict)

        return rows

    def summarize(self) -> Dict[str, Any]:
        """
        Compute a comprehensive engineering & tuning summary of the datalog
        (peak RPM, WOT AFR accuracy, fuel pressure under load, knock, thermal peaks).
        """
        rows = self.parse_rows()
        if not rows:
            return {"error": "No rows parsed"}

        duration_s = rows[-1].get("timestamp_s", 0.0) if rows else 0.0
        channels_summary: Dict[str, Dict[str, float]] = {}

        tracked = [
            "rpm", "map_kpa", "boost_psig", "tps", "target_afr", "afr_avg",
            "current_learn", "closed_loop_comp", "fuel_pw", "injector_duty",
            "fuel_flow", "ignition_timing", "knock_retard", "coolant_temp",
            "iat", "battery_voltage", "oil_pressure", "fuel_pressure",
            "trans_gear", "vehicle_speed", "trans_temp",
        ]

        for ch in tracked:
            vals = [r[ch] for r in rows if ch in r]
            if vals:
                channels_summary[ch] = {
                    "min": round(min(vals), 2),
                    "max": round(max(vals), 2),
                    "avg": round(sum(vals) / len(vals), 2),
                    "last": round(vals[-1], 2),
                }

        # Analyze WOT (TPS >= 85%)
        wot_rows = [r for r in rows if r.get("tps", 0.0) >= 85.0]
        wot_summary: Dict[str, Any] = {"wot_samples": len(wot_rows)}
        if wot_rows:
            wot_rpm_max = max(r.get("rpm", 0.0) for r in wot_rows)
            wot_afr_avg = sum(r.get("afr_avg", 0.0) for r in wot_rows) / len(wot_rows)
            wot_target_afr = sum(r.get("target_afr", 0.0) for r in wot_rows) / len(wot_rows)
            wot_fuel_psi_min = min(r.get("fuel_pressure", 0.0) for r in wot_rows)
            wot_duty_max = max(r.get("injector_duty", 0.0) for r in wot_rows)
            wot_summary.update({
                "peak_rpm": round(wot_rpm_max, 0),
                "avg_wot_afr": round(wot_afr_avg, 2),
                "avg_wot_target_afr": round(wot_target_afr, 2),
                "afr_error": round(wot_afr_avg - wot_target_afr, 2),
                "min_wot_fuel_pressure_psi": round(wot_fuel_psi_min, 1),
                "max_injector_duty_pct": round(wot_duty_max, 1),
            })

        return {
            "filename": self.file_path.name,
            "path": str(self.file_path),
            "file_size_bytes": len(self.dl_data),
            "was_compressed_dlz": self.was_compressed,
            "version": self.format_info["version"],
            "embedded_tune": self.format_info.get("embedded_tune", ""),
            "num_rows": self.format_info["num_rows"],
            "duration_s": round(duration_s, 2),
            "sample_rate_hz": round(self.format_info["num_rows"] / max(duration_s, 0.001), 1),
            "channels": channels_summary,
            "wot_analysis": wot_summary,
        }

    def to_decoded_frames(self, row_index: int = -1) -> List[DecodedFrame]:
        """
        Convert a specific row (default: peak RPM row if row_index == -1) into
        DecodedFrame objects so it can be injected directly into CANListener.
        """
        rows = self.parse_rows()
        if not rows:
            return []

        if row_index < 0:
            # Pick the highest RPM row for maximum diagnostic value on the dashboard
            target_row = max(rows, key=lambda r: r.get("rpm", 0.0))
        else:
            target_row = rows[min(row_index, len(rows) - 1)]

        now = time.time()
        frames: List[DecodedFrame] = []
        for ch_name, val in target_row.items():
            ch_def = CHANNEL_BY_NAME.get(ch_name)
            if ch_def is None:
                continue
            can_id = (1 << 28) | (0b111 << 25) | (ch_def.index << 14) | (0b010 << 11) | 0x1A5
            raw_data = struct.pack(">ff", float(val), 0.0)
            frames.append(
                DecodedFrame(
                    timestamp=now,
                    channel_index=ch_def.index,
                    channel_def=ch_def,
                    value_a=float(val),
                    value_b=0.0,
                    raw_id=can_id,
                    raw_data=raw_data,
                    ecu_serial_bits=0x1A5,
                    protocol="datalog",
                )
            )
        return frames


def discover_local_holley_files(extra_dirs: Optional[List[str | Path]] = None) -> Dict[str, Any]:
    """
    Scan standard Windows Holley Terminator X directories, Google Drive,
    and removable drives for .dl, .dlz, .terx, .hefi, and .gcfgx files.
    Dynamically adapts to whatever user account/laptop executes the code.
    """
    home = Path.home()
    userprofile = Path(os.environ.get("USERPROFILE", str(home)))

    search_roots: List[Path] = [
        # Standard user Documents & OneDrive paths (dynamically resolved on laptop)
        userprofile / "OneDrive" / "Documents" / "Holley",
        userprofile / "Documents" / "Holley",
        home / "OneDrive" / "Documents" / "Holley",
        home / "Documents" / "Holley",
        # Current execution directory & data folder
        Path.cwd(),
        Path.cwd() / "data",
        Path.cwd() / "data" / "uploads",
        Path("./data"),
        Path("./data/uploads"),
    ]

    # Search for Google Drive / My Drive across all common drive letters
    if os.name == "nt":
        for letter in ["C", "D", "E", "F", "G", "H"]:
            drive = Path(f"{letter}:/")
            if drive.exists():
                for sub in ["My Drive/Holley", "Google Drive/Holley", "Holley"]:
                    candidate = drive / sub
                    if candidate.exists():
                        search_roots.append(candidate)

    if extra_dirs:
        for d in extra_dirs:
            p = Path(d)
            if p.exists():
                search_roots.append(p)

    # Deduplicate search roots preserving order
    valid_roots: List[Path] = []
    seen_roots: set[str] = set()
    for r in search_roots:
        if r.exists():
            resolved = str(r.resolve())
            if resolved not in seen_roots:
                seen_roots.add(resolved)
                valid_roots.append(r)

    datalogs: List[Dict[str, Any]] = []
    tunes: List[Dict[str, Any]] = []
    seen_files: set[str] = set()

    tune_extensions = (".terx", ".hefi", ".gcfgx")

    for root in valid_roots:
        try:
            for dirpath, _, filenames in os.walk(root):
                for fn in filenames:
                    ext = os.path.splitext(fn)[1].lower()
                    if ext not in (".dl", ".dlz", *tune_extensions):
                        continue
                    full_path = Path(dirpath) / fn
                    norm = str(full_path.resolve())
                    if norm in seen_files:
                        continue
                    seen_files.add(norm)
                    try:
                        stat = full_path.stat()
                        entry = {
                            "name": fn,
                            "path": norm,
                            "size_bytes": stat.st_size,
                            "modified": stat.st_mtime,
                            "folder": Path(dirpath).name,
                            "type": "tune" if ext in tune_extensions else "datalog",
                        }
                        if ext in (".dl", ".dlz"):
                            datalogs.append(entry)
                        elif ext in tune_extensions:
                            tunes.append(entry)
                    except OSError:
                        pass
        except Exception:
            pass

    datalogs.sort(key=lambda x: x["modified"], reverse=True)
    tunes.sort(key=lambda x: x["modified"], reverse=True)
    return {
        "datalogs": datalogs,
        "tunes": tunes,
        "watched_roots": [str(r.resolve()) for r in valid_roots],
    }

