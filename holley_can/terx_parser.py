"""
terx_parser.py — Reverse-Engineered Binary Parser & Writer for Holley Terminator X (.terx) Tune Files

Reverse Engineered Specification:
  Container Magic:     0xDEEDBEAF (uint32 LE: af be ed de)
  Header:              24 bytes [magic, v1=4, v2=12, v3=239, v4=3, chunk_start=4464]
  ICF Directory:       Array of 264-byte records (offset 24 to 0x1170)
  Chunk Chain:         Offset 0x117c to EOF
                       Each chunk: [block_id: uint32 LE, block_type: uint32 LE, length: uint32 LE]
                       where length covers the 12-byte header + payload (pos += length).
  Footer & Checksum:   Last chunk id = 0xff000000, type = 1, length = 16 (0x10)
                       Last 4 bytes: IEEE 802.3 CRC-32 (poly 0xEDB88320) calculated
                       over all preceding file bytes (data[:-4]), stored in big-endian byte order.
  Fuel ICF (0x00a7):   Contains the 16x16 Fuel VE Table:
                       - MAP axis breakpoints (16 float32s, 64 bytes) @ chunk_offset + 0x538
                       - Fuel VE table matrix (16x16 = 256 float32s, 1024 bytes) @ chunk_offset + 0x5cc
                       - RPM axis breakpoints (16 float32s, 64 bytes) @ chunk_offset + 0x9cc
  Spark ICF (0x00a1):  Contains the 16x16 Base Spark Timing Table:
                       - Timing matrix (16x16 = 256 float32s, 1024 bytes) @ file offset ~0x043dc
"""

from __future__ import annotations

import glob
import logging
import os
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

TERX_MAGIC = 0xDEEDBEAF
CHUNK_FOOTER_ID = 0xFF000000

# Chunk IDs for Terminator X ICFs
CHUNK_ID_FUEL_CONFIG = 0x00A0
CHUNK_ID_SPARK_CONFIG = 0x00A1
CHUNK_ID_SYSTEM = 0x00A2
CHUNK_ID_FUEL_TABLES = 0x00A7   # Holds 16x16 VE Table & axes
CHUNK_ID_ADVANCED = 0x00A8
CHUNK_ID_IO = 0x00A9
CHUNK_ID_TRANSMISSION = 0x00AC

# Relative offsets inside Fuel Tables Chunk (0x00A7)
CHUNK_A7_MAP_AXIS_OFFSET = 0x538
CHUNK_A7_VE_TABLE_OFFSET = 0x5CC
CHUNK_A7_RPM_AXIS_OFFSET = 0x9CC


class TerxFormatError(Exception):
    """Raised when a .terx file has invalid magic, corrupt chunks, or failed checksum."""
    pass


@dataclass
class TerxChunk:
    block_id: int
    block_type: int
    length: int
    payload: bytes  # Data excluding the 12-byte chunk header
    file_offset: int = 0

    def to_bytes(self) -> bytes:
        total_len = len(self.payload) + 12
        header = struct.pack('<III', self.block_id, self.block_type, total_len)
        return header + self.payload


@dataclass
class TerxCalibration:
    """
    In-memory representation of a Holley Terminator X .terx calibration file.
    Supports reading, inspecting, modifying VE/Spark tables, and saving with verified CRC.
    """
    filepath: Optional[Path] = None
    raw_data: bytearray = field(default_factory=bytearray)
    header_bytes: bytes = b''
    icf_directory_bytes: bytes = b''
    chunks: List[TerxChunk] = field(default_factory=list)
    checksum_verified: bool = False
    stored_crc: int = 0
    calculated_crc: int = 0

    # Decoded primary tables
    map_axis: List[float] = field(default_factory=list)
    rpm_axis: List[float] = field(default_factory=list)
    ve_table: List[List[float]] = field(default_factory=list)  # 16 rows (MAP) x 16 cols (RPM)
    base_spark_table: Optional[List[List[float]]] = None

    # Metadata strings
    tune_comment: str = ""
    wizard_version: str = ""

    @classmethod
    def from_bytes(cls, data: Union[bytes, bytearray], filepath: Optional[Union[str, Path]] = None) -> 'TerxCalibration':
        """Parse a .terx binary byte stream."""
        if len(data) < 24 + 16:
            raise TerxFormatError(f"File too small for .terx format: {len(data)} bytes")

        raw = bytearray(data)
        magic = struct.unpack('<I', raw[:4])[0]
        if magic != TERX_MAGIC:
            raise TerxFormatError(f"Invalid magic number 0x{magic:08x}, expected 0x{TERX_MAGIC:08x}")

        # Verify IEEE 802.3 CRC-32 (stored in big-endian at the last 4 bytes)
        stored_crc = struct.unpack('>I', raw[-4:])[0]
        calculated_crc = zlib.crc32(raw[:-4]) & 0xFFFFFFFF
        checksum_ok = (stored_crc == calculated_crc)

        inst = cls(
            filepath=Path(filepath) if filepath else None,
            raw_data=raw,
            checksum_verified=checksum_ok,
            stored_crc=stored_crc,
            calculated_crc=calculated_crc,
        )

        # Header (24 bytes) & ICF directory (up to 0x1170)
        inst.header_bytes = bytes(raw[:24])
        chunk_start = struct.unpack('<I', raw[20:24])[0]
        # In standard files chunk_start is 0x1170, chunks begin at 0x117c (12 bytes after)
        inst.icf_directory_bytes = bytes(raw[24:0x1170])

        # Extract comments / metadata from ICF directory
        inst._extract_metadata()

        # Parse chunks
        pos = 0x117C
        while pos < len(raw):
            if pos + 12 > len(raw):
                break
            b_id, b_type, length = struct.unpack('<III', raw[pos:pos+12])
            if length < 12 or pos + length > len(raw):
                # Malformed chunk length
                break
            payload = bytes(raw[pos+12 : pos+length])
            chunk = TerxChunk(
                block_id=b_id,
                block_type=b_type,
                length=length,
                payload=payload,
                file_offset=pos,
            )
            inst.chunks.append(chunk)
            if b_id == CHUNK_FOOTER_ID:
                break
            pos += length

        # Decode VE Table and axes from Chunk 0x00A7
        inst._decode_fuel_tables()
        # Decode Spark Table from Chunk 0x00A1 if present
        inst._decode_spark_tables()

        return inst

    @classmethod
    def from_file(cls, filepath: Union[str, Path]) -> 'TerxCalibration':
        """Load and parse a .terx file from disk."""
        p = Path(filepath)
        if not p.exists():
            raise FileNotFoundError(f"File not found: {filepath}")
        data = p.read_bytes()
        return cls.from_bytes(data, filepath=p)

    def _extract_metadata(self) -> None:
        """Scan ICF directory strings for tune comments and wizard versions."""
        try:
            # Look for null-terminated ASCII strings in the ICF header
            sub = self.raw_data[24:0x1170]
            # Strip zeroes and find printable segments
            import re
            strings = [s.decode('latin1', errors='ignore') for s in re.findall(rb'[\x20-\x7e]{4,}', sub)]
            for s in strings:
                if "Wizard Version" in s or "Terminator X" in s:
                    self.wizard_version = s
                elif not self.tune_comment and not s.endswith(".terx") and not s.endswith(".io") and not s.endswith(".adv") and not s.endswith(".fuel"):
                    self.tune_comment = s
        except Exception as e:
            logger.debug("Failed to extract metadata strings: %s", e)

    def _decode_fuel_tables(self) -> None:
        """Extract MAP axis, RPM axis, and 16x16 Fuel VE table from chunk 0x00A7."""
        fuel_chunk = next((c for c in self.chunks if c.block_id == CHUNK_ID_FUEL_TABLES), None)
        if not fuel_chunk:
            logger.warning("Chunk 0x00A7 (Fuel Tables) not found in calibration")
            return

        payload = fuel_chunk.payload
        # Note: chunk offsets inside payload are relative to payload start (chunk_offset - 12)
        # Because CHUNK_A7_MAP_AXIS_OFFSET (0x538) is from chunk start (including 12-byte header),
        # payload offset = offset - 12.
        map_offset = CHUNK_A7_MAP_AXIS_OFFSET - 12
        ve_offset = CHUNK_A7_VE_TABLE_OFFSET - 12
        rpm_offset = CHUNK_A7_RPM_AXIS_OFFSET - 12

        if len(payload) >= rpm_offset + 64:
            self.map_axis = list(struct.unpack('<16f', payload[map_offset : map_offset + 64]))
            self.rpm_axis = list(struct.unpack('<16f', payload[rpm_offset : rpm_offset + 64]))
            
            flat_ve = struct.unpack('<256f', payload[ve_offset : ve_offset + 1024])
            self.ve_table = []
            for r in range(16):
                row = list(flat_ve[r * 16 : (r + 1) * 16])
                self.ve_table.append(row)

    def _decode_spark_tables(self) -> None:
        """Locate and decode 16x16 Base Spark Timing table in Spark ICF chunk."""
        spark_chunk = next((c for c in self.chunks if c.block_id == CHUNK_ID_SPARK_CONFIG), None)
        if not spark_chunk:
            return

        payload = spark_chunk.payload
        # In Spark ICF, the 16x16 timing table is located by searching for 256 floats in range [-10, 60]
        # or at standard offset. Let's scan payload for 256 float timing grid
        for i in range(0, len(payload) - 1024, 4):
            floats = struct.unpack('<256f', payload[i : i + 1024])
            if all(-10.0 <= x <= 65.0 for x in floats):
                avg = sum(floats) / 256.0
                if 12.0 <= avg <= 36.0 and len(set(floats)) > 15:
                    self.base_spark_table = [list(floats[r * 16 : (r + 1) * 16]) for r in range(16)]
                    break

    def get_ve_cell(self, row: int, col: int) -> float:
        """Get VE table cell value at [row (MAP), col (RPM)]."""
        if not (0 <= row < 16 and 0 <= col < 16):
            raise IndexError(f"Cell coordinates out of bounds: [{row}, {col}]")
        return self.ve_table[row][col]

    def set_ve_cell(self, row: int, col: int, value: float) -> None:
        """Set a single VE cell value."""
        if not (0 <= row < 16 and 0 <= col < 16):
            raise IndexError(f"Cell coordinates out of bounds: [{row}, {col}]")
        self.ve_table[row][col] = float(value)
        self._sync_ve_table_to_chunk()

    def update_ve_table(self, new_table: List[List[float]]) -> None:
        """
        Update the entire 16x16 Fuel VE table matrix.
        Accepts 16 rows of 16 float values.
        """
        if len(new_table) != 16 or any(len(row) != 16 for row in new_table):
            raise ValueError("new_table must be a 16x16 2D matrix")
        self.ve_table = [[float(val) for val in row] for row in new_table]
        self._sync_ve_table_to_chunk()

    def _sync_ve_table_to_chunk(self) -> None:
        """Serialize current in-memory ve_table back into Chunk 0x00A7 payload and raw_data."""
        fuel_chunk = next((c for c in self.chunks if c.block_id == CHUNK_ID_FUEL_TABLES), None)
        if not fuel_chunk:
            raise TerxFormatError("Cannot sync VE table: Chunk 0x00A7 not found")

        flat_floats = [val for row in self.ve_table for val in row]
        ve_bytes = struct.pack('<256f', *flat_floats)

        ve_payload_offset = CHUNK_A7_VE_TABLE_OFFSET - 12
        p_bytearray = bytearray(fuel_chunk.payload)
        p_bytearray[ve_payload_offset : ve_payload_offset + 1024] = ve_bytes
        fuel_chunk.payload = bytes(p_bytearray)

        # Also update raw_data at absolute offset
        abs_ve_offset = fuel_chunk.file_offset + CHUNK_A7_VE_TABLE_OFFSET
        self.raw_data[abs_ve_offset : abs_ve_offset + 1024] = ve_bytes

    def to_bytes(self) -> bytes:
        """
        Reassemble the entire .terx file binary, recomputing the CRC-32 footer checksum.
        Guarantees that the returned binary passes all Terminator X checksum validations.
        """
        # Re-pack raw bytes up to the footer checksum
        # We preserve header & ICF directory and serialize chunks
        buf = bytearray(self.raw_data[:0x117C])

        for chunk in self.chunks:
            if chunk.block_id == CHUNK_FOOTER_ID:
                # Footer chunk is 16 bytes: [id=0xff000000, type=1, len=16, crc32]
                footer_header = struct.pack('<III', CHUNK_FOOTER_ID, 1, 16)
                buf.extend(footer_header)
                # Compute IEEE 802.3 CRC-32 over everything up to this point
                calculated_crc = zlib.crc32(buf) & 0xFFFFFFFF
                # Store CRC-32 in big-endian order (Holley bswap standard)
                buf.extend(struct.pack('>I', calculated_crc))
                self.calculated_crc = calculated_crc
                self.stored_crc = calculated_crc
                self.checksum_verified = True
                break
            else:
                buf.extend(chunk.to_bytes())

        self.raw_data = buf
        return bytes(buf)

    def save(self, output_path: Union[str, Path]) -> Path:
        """Save the calibration to disk with a verified CRC-32 checksum."""
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        data = self.to_bytes()
        out.write_bytes(data)
        logger.info("Saved verified .terx calibration to %s (%d bytes, CRC=0x%08X)", out, len(data), self.calculated_crc)
        return out

    def to_dict(self) -> Dict[str, Any]:
        """Convert calibration metadata, axes, and VE table into a JSON-friendly dict."""
        return {
            "filepath": str(self.filepath) if self.filepath else None,
            "filename": self.filepath.name if self.filepath else "in_memory.terx",
            "filesize_bytes": len(self.raw_data),
            "checksum_verified": self.checksum_verified,
            "stored_crc": f"0x{self.stored_crc:08X}",
            "calculated_crc": f"0x{self.calculated_crc:08X}",
            "tune_comment": self.tune_comment,
            "wizard_version": self.wizard_version,
            "map_axis": [round(x, 1) for x in self.map_axis],
            "rpm_axis": [int(round(x)) for x in self.rpm_axis],
            "ve_table": [[round(cell, 2) for cell in row] for row in self.ve_table],
            "has_spark_table": self.base_spark_table is not None,
            "spark_table": [[round(cell, 1) for cell in row] for row in self.base_spark_table] if self.base_spark_table else None,
        }


def discover_terx_files(search_paths: Optional[List[Union[str, Path]]] = None) -> List[Path]:
    """
    Search standard local directories for Holley Terminator X .terx calibration files.
    """
    if not search_paths:
        home = Path.home()
        search_paths = [
            home / "Desktop",
            home / "OneDrive" / "Desktop",
            home / "Documents" / "Holley",
            home / "OneDrive" / "Documents" / "Holley",
            Path(r"G:\My Drive\Holley"),
        ]

    found: List[Path] = []
    seen = set()

    for p in search_paths:
        base = Path(p)
        if not base.exists():
            continue
        try:
            for f in base.rglob("*.terx"):
                abs_str = str(f.resolve()).lower()
                if abs_str not in seen:
                    seen.add(abs_str)
                    found.append(f)
        except Exception as e:
            logger.debug("Error scanning %s for .terx files: %s", base, e)

    # Sort files by modification time (most recent first)
    found.sort(key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True)
    return found


def clone_and_apply_ve(
    source_terx: Union[str, Path],
    target_terx: Union[str, Path],
    new_ve_table: List[List[float]],
) -> TerxCalibration:
    """
    Load an existing .terx calibration, apply a new 16x16 VE matrix, and save to a new file with verified CRC.
    """
    cal = TerxCalibration.from_file(source_terx)
    cal.update_ve_table(new_ve_table)
    cal.save(target_terx)
    return cal

