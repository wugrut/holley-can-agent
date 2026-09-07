"""
test_protocol.py — Unit tests for the HEFI CAN protocol decoder.

Tests CAN ID extraction, payload decoding, frame classification,
and channel mapping using known frame examples.
"""

import struct
import time
import pytest

from holley_can.protocol import (
    CHANNEL_MAP,
    CHANNEL_BY_NAME,
    DecodedFrame,
    ChannelCategory,
    decode_frame,
    decode_payload,
    extract_channel_index,
    extract_ecu_serial,
    is_hefi_broadcast,
)


# ─── Test Helpers ────────────────────────────────────────────────────────────

def make_hefi_can_id(channel_index: int, ecu_serial: int = 0x1A5) -> int:
    """
    Construct a valid HEFI broadcast CAN ID.

    Bit layout:
      28:    1 (command/broadcast)
      27:25: 111 (broadcast target)
      24:14: channel_index
      13:11: 010 (ECU source)
      10:0:  ecu_serial & 0x7FF
    """
    can_id = 0
    can_id |= (1 << 28)                         # Command bit
    can_id |= (0b111 << 25)                      # Broadcast target
    can_id |= ((channel_index & 0x7FF) << 14)    # Channel index
    can_id |= (0b010 << 11)                      # ECU source
    can_id |= (ecu_serial & 0x7FF)               # Serial
    return can_id


def make_payload(value_a: float, value_b: float = 0.0) -> bytes:
    """Create an 8-byte payload with two big-endian floats."""
    return struct.pack(">ff", value_a, value_b)


# ─── CAN ID Tests ────────────────────────────────────────────────────────────

class TestCANIDExtraction:
    def test_extract_channel_index_rpm(self):
        """Channel index 1 (RPM) should be extractable from a constructed ID."""
        can_id = make_hefi_can_id(channel_index=1, ecu_serial=0x1A5)
        assert extract_channel_index(can_id) == 1

    def test_extract_channel_index_map(self):
        can_id = make_hefi_can_id(channel_index=2, ecu_serial=0x0FF)
        assert extract_channel_index(can_id) == 2

    def test_extract_channel_index_high(self):
        can_id = make_hefi_can_id(channel_index=32, ecu_serial=0x7FF)
        assert extract_channel_index(can_id) == 32

    def test_extract_ecu_serial(self):
        can_id = make_hefi_can_id(channel_index=1, ecu_serial=0x1A5)
        assert extract_ecu_serial(can_id) == 0x1A5

    def test_extract_ecu_serial_max(self):
        can_id = make_hefi_can_id(channel_index=1, ecu_serial=0x7FF)
        assert extract_ecu_serial(can_id) == 0x7FF

    def test_extract_ecu_serial_zero(self):
        can_id = make_hefi_can_id(channel_index=1, ecu_serial=0x000)
        assert extract_ecu_serial(can_id) == 0x000

    def test_different_serials_same_channel(self):
        """Different ECU serials should yield the same channel index."""
        id_a = make_hefi_can_id(channel_index=5, ecu_serial=0x100)
        id_b = make_hefi_can_id(channel_index=5, ecu_serial=0x200)
        assert extract_channel_index(id_a) == extract_channel_index(id_b) == 5


class TestHEFIBroadcastValidation:
    def test_valid_broadcast(self):
        can_id = make_hefi_can_id(channel_index=1)
        assert is_hefi_broadcast(can_id) is True

    def test_live_terminator_x_broadcast_frames(self):
        """Validates real-world Terminator X broadcast frames captured on live vehicle."""
        # Frame 1: Coolant Enrichment (ch 10)
        assert is_hefi_broadcast(0x1002AAB4) is True
        assert extract_channel_index(0x1002AAB4) == 10
        # Frame 2: AFR Bank 1 (ch 6)
        assert is_hefi_broadcast(0x10018124) is True
        assert extract_channel_index(0x10018124) == 6

    def test_invalid_cmd_bit(self):
        """If the command bit (28) is 0, it's not a broadcast."""
        can_id = make_hefi_can_id(channel_index=1)
        can_id &= ~(1 << 28)  # Clear cmd bit
        assert is_hefi_broadcast(can_id) is False

    def test_invalid_channel_index(self):
        """Channel index 0 is not a valid broadcast."""
        can_id = 0x10000000  # channel_index == 0
        assert is_hefi_broadcast(can_id) is False



# ─── Payload Tests ───────────────────────────────────────────────────────────

class TestPayloadDecoding:
    def test_decode_known_values(self):
        data = make_payload(3500.0, 0.0)
        a, b = decode_payload(data)
        assert abs(a - 3500.0) < 0.01
        assert abs(b - 0.0) < 0.01

    def test_decode_afr_value(self):
        data = make_payload(14.7, 1.0)
        a, b = decode_payload(data)
        assert abs(a - 14.7) < 0.01
        assert abs(b - 1.0) < 0.01

    def test_decode_negative_timing(self):
        data = make_payload(-5.0, 0.0)
        a, b = decode_payload(data)
        assert abs(a - (-5.0)) < 0.01

    def test_invalid_payload_length(self):
        with pytest.raises(ValueError):
            decode_payload(b"\x00\x01\x02")


# ─── Full Frame Decoding ────────────────────────────────────────────────────

class TestFrameDecoding:
    def test_decode_rpm_frame(self):
        can_id = make_hefi_can_id(channel_index=1, ecu_serial=0x1A5)
        data = make_payload(3500.0, 0.0)
        ts = time.time()

        frame = decode_frame(can_id, data, ts)

        assert frame.channel_index == 1
        assert frame.channel_def is not None
        assert frame.channel_def.name == "rpm"
        assert frame.name == "rpm"
        assert frame.label == "RPM"
        assert frame.unit == "rpm"
        assert abs(frame.value_a - 3500.0) < 0.01
        assert frame.ecu_serial_bits == 0x1A5

    def test_decode_map_frame(self):
        can_id = make_hefi_can_id(channel_index=2, ecu_serial=0x0FF)
        data = make_payload(101.325, 101.0)
        ts = time.time()

        frame = decode_frame(can_id, data, ts)

        assert frame.name == "map_kpa"
        assert abs(frame.value_a - 101.325) < 0.01
        assert abs(frame.value_b - 101.0) < 0.01

    def test_decode_unknown_channel(self):
        """Unknown channel index should still decode, but with no channel_def."""
        can_id = make_hefi_can_id(channel_index=999, ecu_serial=0x1A5)
        data = make_payload(42.0, 0.0)
        ts = time.time()

        frame = decode_frame(can_id, data, ts)

        assert frame.channel_def is None
        assert frame.name == "unknown_999"
        assert frame.label == "Channel 999"
        assert frame.unit == ""

    def test_decode_timing_frame(self):
        can_id = make_hefi_can_id(channel_index=11, ecu_serial=0x1A5)
        data = make_payload(28.5, 0.0)
        ts = time.time()

        frame = decode_frame(can_id, data, ts)

        assert frame.name == "ignition_timing"
        assert abs(frame.value_a - 28.5) < 0.01

    def test_decode_gear_frame(self):
        can_id = make_hefi_can_id(channel_index=20, ecu_serial=0x1A5)
        data = make_payload(3.0, 0.0)
        ts = time.time()

        frame = decode_frame(can_id, data, ts)

        assert frame.name == "trans_gear"
        assert frame.channel_def.category == ChannelCategory.TRANSMISSION
        assert abs(frame.value_a - 3.0) < 0.01


# ─── Channel Map Tests ──────────────────────────────────────────────────────

class TestChannelMap:
    def test_all_channels_have_unique_names(self):
        names = [ch.name for ch in CHANNEL_MAP.values()]
        assert len(names) == len(set(names)), "Duplicate channel names found"

    def test_critical_channels_exist(self):
        required = ["rpm", "map_kpa", "target_afr", "afr_avg",
                     "ignition_timing", "coolant_temp", "battery_voltage",
                     "trans_gear", "tcc_status"]
        for name in required:
            assert name in CHANNEL_BY_NAME, f"Missing critical channel: {name}"

    def test_channel_by_name_lookup(self):
        ch = CHANNEL_BY_NAME["rpm"]
        assert ch.index == 1
        assert ch.category == ChannelCategory.ENGINE
