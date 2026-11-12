"""
test_terx_parser.py — Unit Tests for Holley Terminator X (.terx) Binary Parser and Checksum Engine
"""

import glob
import os
import struct
import zlib
from pathlib import Path
import pytest

from holley_can.terx_parser import (
    CHUNK_A7_MAP_AXIS_OFFSET,
    CHUNK_A7_RPM_AXIS_OFFSET,
    CHUNK_A7_VE_TABLE_OFFSET,
    CHUNK_FOOTER_ID,
    CHUNK_ID_FUEL_TABLES,
    TERX_MAGIC,
    TerxCalibration,
    TerxChunk,
    TerxFormatError,
    clone_and_apply_ve,
    discover_terx_files,
)


def _build_synthetic_terx(
    map_axis=None,
    rpm_axis=None,
    ve_matrix=None,
) -> bytes:
    """Helper to build a valid minimal synthetic .terx binary with real chunks and verified CRC."""
    if map_axis is None:
        map_axis = [float(i * 7) for i in range(16)]
    if rpm_axis is None:
        rpm_axis = [float(800 + i * 400) for i in range(16)]
    if ve_matrix is None:
        ve_matrix = [[50.0 + r + c * 2.0 for c in range(16)] for r in range(16)]

    # 1. Header (24 bytes)
    header = struct.pack('<IIIIII', TERX_MAGIC, 4, 12, 239, 3, 0x1170)

    # 2. ICF Directory (pad to 0x1170 bytes = 4464 bytes)
    comment = b"Synthetic Fairmont Test Cal\x00Wizard 1.4\x00"
    icf_dir = comment + b'\x00' * (0x1170 - 24 - len(comment))

    # 3. Intermediate dummy padding up to 0x117C (12 bytes)
    gap = b'\x00' * 12

    # 4. Chunk 0x00A7 (Fuel Tables)
    # Needs to be at least 0x9CC + 64 bytes = 2572 bytes
    payload_len = 3000
    payload = bytearray(b'\x00' * payload_len)

    # Write MAP axis @ (CHUNK_A7_MAP_AXIS_OFFSET - 12)
    map_off = CHUNK_A7_MAP_AXIS_OFFSET - 12
    struct.pack_into('<16f', payload, map_off, *map_axis)

    # Write VE table @ (CHUNK_A7_VE_TABLE_OFFSET - 12)
    ve_off = CHUNK_A7_VE_TABLE_OFFSET - 12
    flat_ve = [val for row in ve_matrix for val in row]
    struct.pack_into('<256f', payload, ve_off, *flat_ve)

    # Write RPM axis @ (CHUNK_A7_RPM_AXIS_OFFSET - 12)
    rpm_off = CHUNK_A7_RPM_AXIS_OFFSET - 12
    struct.pack_into('<16f', payload, rpm_off, *rpm_axis)

    chunk_a7 = struct.pack('<III', CHUNK_ID_FUEL_TABLES, 3, len(payload) + 12) + bytes(payload)

    # 5. Footer Chunk (16 bytes)
    footer_header = struct.pack('<III', CHUNK_FOOTER_ID, 1, 16)

    # Assemble everything before CRC
    raw_before_crc = header + icf_dir + gap + chunk_a7 + footer_header

    # Compute CRC-32 and append big-endian
    crc = zlib.crc32(raw_before_crc) & 0xFFFFFFFF
    raw_complete = raw_before_crc + struct.pack('>I', crc)

    return raw_complete


def test_synthetic_terx_parse_and_verify():
    data = _build_synthetic_terx()
    cal = TerxCalibration.from_bytes(data)

    assert cal.checksum_verified is True
    assert cal.stored_crc == cal.calculated_crc
    assert len(cal.map_axis) == 16
    assert len(cal.rpm_axis) == 16
    assert len(cal.ve_table) == 16
    assert len(cal.ve_table[0]) == 16
    assert cal.get_ve_cell(0, 0) == 50.0
    assert cal.tune_comment == "Synthetic Fairmont Test Cal"


def test_invalid_magic_raises_error():
    data = bytearray(_build_synthetic_terx())
    data[0:4] = b'\x00\x00\x00\x00'
    with pytest.raises(TerxFormatError, match="Invalid magic number"):
        TerxCalibration.from_bytes(data)


def test_corrupt_checksum_flag():
    data = bytearray(_build_synthetic_terx())
    # Modify one byte in the payload without recomputing CRC
    data[0x1200] ^= 0xFF
    cal = TerxCalibration.from_bytes(data)
    assert cal.checksum_verified is False
    assert cal.stored_crc != cal.calculated_crc


def test_update_ve_cell_and_save(tmp_path):
    data = _build_synthetic_terx()
    src_file = tmp_path / "test_orig.terx"
    src_file.write_bytes(data)

    cal = TerxCalibration.from_file(src_file)
    assert cal.get_ve_cell(5, 5) == 50.0 + 5 + 10.0

    # Modify cell and save
    cal.set_ve_cell(5, 5, 88.5)
    out_file = tmp_path / "test_modified.terx"
    cal.save(out_file)

    # Reload from disk and verify
    reloaded = TerxCalibration.from_file(out_file)
    assert reloaded.checksum_verified is True
    assert reloaded.get_ve_cell(5, 5) == 88.5
    assert reloaded.calculated_crc == reloaded.stored_crc


def test_update_full_ve_table(tmp_path):
    data = _build_synthetic_terx()
    src_file = tmp_path / "test_full.terx"
    src_file.write_bytes(data)

    cal = TerxCalibration.from_file(src_file)
    new_matrix = [[100.0 for _ in range(16)] for _ in range(16)]
    cal.update_ve_table(new_matrix)

    out_file = tmp_path / "test_full_out.terx"
    cal.save(out_file)

    reloaded = TerxCalibration.from_file(out_file)
    assert reloaded.checksum_verified is True
    assert reloaded.ve_table[0][0] == 100.0
    assert reloaded.ve_table[15][15] == 100.0


def test_clone_and_apply_ve(tmp_path):
    data = _build_synthetic_terx()
    src = tmp_path / "source.terx"
    dst = tmp_path / "cloned.terx"
    src.write_bytes(data)

    new_ve = [[75.0 for _ in range(16)] for _ in range(16)]
    cal = clone_and_apply_ve(src, dst, new_ve)

    assert dst.exists()
    assert cal.checksum_verified is True
    reloaded = TerxCalibration.from_file(dst)
    assert reloaded.get_ve_cell(8, 8) == 75.0


def test_to_dict_structure():
    data = _build_synthetic_terx()
    cal = TerxCalibration.from_bytes(data)
    d = cal.to_dict()

    assert "map_axis" in d
    assert "rpm_axis" in d
    assert "ve_table" in d
    assert d["checksum_verified"] is True
    assert len(d["ve_table"]) == 16


def test_real_terx_if_available():
    # If desktop or base cal files are present, verify on actual vehicle tunes
    real_files = glob.glob(r'C:\Users\wugrut\OneDrive\Desktop\*Fairmont*.terx')
    if not real_files:
        real_files = glob.glob(r'C:\Users\wugrut\OneDrive\Documents\Holley\**\*.terx', recursive=True)

    if real_files:
        test_file = real_files[0]
        cal = TerxCalibration.from_file(test_file)
        assert cal.checksum_verified is True
        assert len(cal.ve_table) == 16
        assert len(cal.ve_table[0]) == 16
        assert len(cal.map_axis) == 16
        assert len(cal.rpm_axis) == 16
        print(f"\nSuccessfully verified real calibration: {Path(test_file).name} (CRC={cal.stored_crc:08X})")

