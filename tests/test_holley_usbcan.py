"""
Unit and integration tests for HolleyUsbCanAdapter and USB frame protocol parsing.

[MOCKED HARDWARE TEST SUITE]
Physical hardware testing with the actual Holley 558-443 cable and Terminator X MAX
is performed live on the target tuning laptop.
"""

from __future__ import annotations

import asyncio
import struct
from unittest.mock import patch
import pytest

from app.can.frame import RawCANFrame
from app.events.detector import EventDetector
from app.hardware.detection import discover_available_adapters
from app.hardware.holley_usbcan import (
    PACKET_SIZE,
    USBC_MAGIC,
    HolleyUsbCanAdapter,
    parse_holley_can_packet,
)
from app.hardware.interface import ConnectionState
from app.protocol.hefi import HefiProtocolDecoder
from app.storage.database import Database
from app.storage.repository import TelemetryRepository


def create_test_packet(can_id: int, dlc: int, payload: bytes) -> bytes:
    """Helper to assemble a valid 20-byte Holley CAN frame packet."""
    padded_payload = payload.ljust(8, b"\x00")[:8]
    return USBC_MAGIC + struct.pack("<IB3s8s", can_id, dlc, b"\x00\x00\x00", padded_payload)


class TestHolleyUsbCanParser:
    """Tests for raw byte frame synchronization and parsing."""

    def test_parse_valid_packet(self) -> None:
        can_id = 0x1E010020
        payload = bytes([0x10, 0x27, 0x00, 0x00, 0x50, 0x00, 0x00, 0x00])
        packet = create_test_packet(can_id, 8, payload)

        assert len(packet) == PACKET_SIZE
        result = parse_holley_can_packet(packet)
        assert result is not None
        parsed_id, parsed_dlc, parsed_data = result
        assert parsed_id == can_id
        assert parsed_dlc == 8
        assert parsed_data == payload

    def test_parse_short_payload(self) -> None:
        can_id = 0x1E001234
        payload = bytes([0xAA, 0xBB, 0xCC, 0xDD])
        packet = create_test_packet(can_id, 4, payload)

        result = parse_holley_can_packet(packet)
        assert result is not None
        parsed_id, parsed_dlc, parsed_data = result
        assert parsed_id == can_id
        assert parsed_dlc == 4
        assert parsed_data == payload

    def test_parse_invalid_magic(self) -> None:
        packet = b"XXXX" + struct.pack("<IB3s8s", 0x100, 8, b"\x00\x00\x00", b"\x00" * 8)
        assert parse_holley_can_packet(packet) is None

    def test_parse_truncated_packet(self) -> None:
        packet = b"USBC\x01\x02"
        assert parse_holley_can_packet(packet) is None

    def test_parse_real_hardware_packet_with_firmware_flags(self) -> None:
        """Physical Holley dongles tag raw frames with upper flags (0x70000000)."""
        raw_id = 0x7002AAB4  # Real packet captured from vehicle Terminator X
        payload = bytes([0x41, 0x20, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        packet = USBC_MAGIC + struct.pack("<IB3s8s", raw_id, 8, b"\x00\x00\x00", payload)

        result = parse_holley_can_packet(packet)
        assert result is not None
        parsed_id, parsed_dlc, parsed_data = result
        assert parsed_id == 0x1002AAB4
        assert parsed_id <= 0x1FFFFFFF

    def test_parse_terminator_x_captured_ids(self) -> None:
        """Verify real captured IDs 0x7000AAB4 (ch 2 MAP) and 0x70018124 (ch 6 AFR Left)."""
        for raw_id, expected_clean, expected_ch in [
            (0x7000AAB4, 0x1000AAB4, 2),
            (0x70018124, 0x10018124, 6),
        ]:
            packet = USBC_MAGIC + struct.pack("<IB3s8s", raw_id, 8, b"\x00\x00\x00", b"\x00" * 8)
            res = parse_holley_can_packet(packet)
            assert res is not None
            clean_id, dlc, _ = res
            assert clean_id == expected_clean
            assert (clean_id >> 14) & 0x7FF == expected_ch

    def test_raw_can_frame_masks_firmware_flags(self) -> None:
        """RawCANFrame should sanitize upper flags into valid 29-bit CAN ID without throwing ValueError."""
        frame = RawCANFrame(
            timestamp=100.0,
            arbitration_id=0x7000AAB4,
            data=b"\x01\x02\x03\x04\x05\x06\x07\x08",
        )
        assert frame.arbitration_id == 0x1000AAB4
        assert frame.arbitration_id <= 0x1FFFFFFF




class TestHolleyUsbCanStreamProcessing:
    """Tests for streaming chunk fragmentation, jitter, and recovery."""

    def test_single_packet_in_chunk(self) -> None:
        adapter = HolleyUsbCanAdapter()
        packet = create_test_packet(0x1E010001, 8, b"\x01\x02\x03\x04\x05\x06\x07\x08")
        adapter._process_stream_chunk(packet)

        assert adapter._status.frames_received == 1
        assert adapter._status.error_frames == 0
        assert len(adapter._stream_buffer) == 0

    def test_multiple_packets_in_single_chunk(self) -> None:
        adapter = HolleyUsbCanAdapter()
        p1 = create_test_packet(0x1E010001, 8, b"\x01" * 8)
        p2 = create_test_packet(0x1E010002, 8, b"\x02" * 8)
        p3 = create_test_packet(0x1E010003, 8, b"\x03" * 8)

        adapter._process_stream_chunk(p1 + p2 + p3)
        assert adapter._status.frames_received == 3
        assert len(adapter._stream_buffer) == 0

    def test_split_packet_across_chunks(self) -> None:
        adapter = HolleyUsbCanAdapter()
        packet = create_test_packet(0x1E010001, 8, b"\xAA" * 8)

        # Send first 7 bytes
        adapter._process_stream_chunk(packet[:7])
        assert adapter._status.frames_received == 0
        assert len(adapter._stream_buffer) == 7

        # Send remaining 13 bytes
        adapter._process_stream_chunk(packet[7:])
        assert adapter._status.frames_received == 1
        assert len(adapter._stream_buffer) == 0

    def test_recovery_from_leading_garbage_noise(self) -> None:
        adapter = HolleyUsbCanAdapter()
        garbage = b"\xFF\xFE\x00\x12\x34\x56"
        packet = create_test_packet(0x1E010001, 8, b"\x55" * 8)

        adapter._process_stream_chunk(garbage + packet)
        assert adapter._status.frames_received == 1
        assert len(adapter._stream_buffer) == 0

    def test_corrupted_fragment_handling(self) -> None:
        adapter = HolleyUsbCanAdapter()
        garbage = b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09"
        adapter._process_stream_chunk(garbage)
        # Retains only the trailing bytes that could potentially start a USBC header
        assert len(adapter._stream_buffer) == 3
        assert adapter._status.frames_received == 0


class TestHolleyUsbCanSafety:
    """[SAFETY INVARIANT TESTS] Enforce passive/listen-only behavior."""

    def test_send_is_strictly_rejected(self) -> None:
        adapter = HolleyUsbCanAdapter()
        dummy_frame = RawCANFrame(
            timestamp=100.0,
            arbitration_id=0x1E010001,
            data=b"\x00" * 8,
            dlc=8,
            channel="HOLLEY_USBCAN_0",
        )
        # Attempting to send MUST return False and never transmit
        result = adapter.send(dummy_frame)
        assert result is False

    def test_initial_state(self) -> None:
        adapter = HolleyUsbCanAdapter()
        assert not adapter.is_connected()
        status = adapter.get_status()
        assert status.state == ConnectionState.DISCONNECTED
        assert status.adapter_name == "HolleyUsbCanAdapter (WinUSB)"
        assert status.channel == "HOLLEY_USBCAN_0"
        assert status.bitrate == 1_000_000

    def test_reset_metrics(self) -> None:
        adapter = HolleyUsbCanAdapter()
        adapter._status.frames_received = 100
        adapter._status.error_frames = 5
        adapter._status.bytes_received = 2000

        adapter.reset_metrics()
        status = adapter.get_status()
        assert status.frames_received == 0
        assert status.error_frames == 0
        assert status.bytes_received == 0

    def test_receive_when_disconnected(self) -> None:
        adapter = HolleyUsbCanAdapter()
        frame = asyncio.run(adapter.receive(timeout=0.01))
        assert frame is None


class TestHolleyUsbCanDetectionMocked:
    """[MOCKED HARDWARE TEST] Tests discovery logic when device is present vs absent."""

    def test_holley_detected_when_cable_present(self) -> None:
        mock_path = r"\\?\usb#vid_2ad0&pid_1005#12345#{abe07f2b-a951-4941-94a4-52adaa1fa53e}"
        with patch("app.hardware.holley_usbcan.enumerate_holley_devices", return_value=[mock_path]):
            adapters = discover_available_adapters()
            holley_entry = next((a for a in adapters if a["adapter_type"] == "holley"), None)
            assert holley_entry is not None
            assert holley_entry["recommended"] is True
            assert holley_entry["cable_connected"] is True
            assert "CONNECTED & READY" in holley_entry["description"]

    def test_holley_reported_when_cable_unplugged(self) -> None:
        with patch("app.hardware.holley_usbcan.enumerate_holley_devices", return_value=[]):
            adapters = discover_available_adapters()
            holley_entry = next((a for a in adapters if a["adapter_type"] == "holley"), None)
            assert holley_entry is not None
            assert holley_entry["cable_connected"] is False
            assert "CABLE UNPLUGGED" in holley_entry["description"]


class TestHolleyUsbCanIntegrationPipeline:
    """[MOCKED HARDWARE TEST] End-to-end flow from USB stream to decoded telemetry."""

    def test_usb_packet_to_telemetry_pipeline(self, tmp_path) -> None:
        # 1. Setup adapter with async queue and mocked connected state
        adapter = HolleyUsbCanAdapter()
        adapter._status.state = ConnectionState.CONNECTED
        adapter._h_winusb = 12345
        loop = asyncio.new_event_loop()
        adapter._loop = loop
        adapter._queue = asyncio.Queue()

        # 2. Assemble HEFI broadcast frame (Channel Index 1 = Engine RPM)
        # HEFI ID: cmd=1 (bit 28), target=7 (bits 25..27), channel=1 (bits 14..24), source=2 (bits 11..13)
        hefi_rpm_can_id = (1 << 28) | (0b111 << 25) | (1 << 14) | (0b010 << 11)
        # Payload for RPM = 3500 (two big-endian floats per HEFI spec)
        payload = struct.pack(">ff", 3500.0, 0.0)

        packet = create_test_packet(hefi_rpm_can_id, 8, payload)

        # 3. Process packet through stream processor
        adapter._process_stream_chunk(packet)
        assert adapter._status.frames_received == 1

        # Run loop briefly to deliver thread-safe queued frame
        async def fetch():
            return await adapter.receive(timeout=0.1)

        frame = loop.run_until_complete(fetch())
        assert frame is not None
        assert frame.arbitration_id == hefi_rpm_can_id

        # 4. Decode frame via HefiProtocolDecoder
        decoder = HefiProtocolDecoder()
        assert decoder.can_decode(frame)
        signals = decoder.decode(frame)
        assert len(signals) > 0
        rpm_signal = signals[0]
        assert rpm_signal.signal_name == "engine_rpm"
        assert abs(rpm_signal.value - 3500.0) < 0.1

        # 5. Persist to SQLite Database
        db_file = tmp_path / "test_holley.db"
        db = Database(str(db_file))
        repo = TelemetryRepository(db)
        repo.insert_session(
            session_id="test_sess_01",
            vehicle_id="terminator_x_max",
            session_type="live_monitor",
            start_time=1700000000.0,
        )
        assert db_file.exists()

        loop.close()
