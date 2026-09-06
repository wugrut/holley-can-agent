"""
Unit tests for the HefiProtocolDecoder and protocol registry.
"""

import struct
import time
import pytest

from app.can.frame import RawCANFrame
from app.hardware.simulator import make_hefi_can_id, pack_payload
from app.protocol.hefi import (
    HefiProtocolDecoder,
    extract_channel_index,
    extract_ecu_serial,
    is_hefi_broadcast,
)
from app.protocol.registry import VERIFIED_CHANNELS


class TestHefiProtocolDecoder:
    def test_decode_rpm_frame(self):
        decoder = HefiProtocolDecoder()
        can_id = make_hefi_can_id(channel_index=1, ecu_serial=0x1A5)
        payload = pack_payload(852.5, 0.0)

        frame = RawCANFrame(
            timestamp=time.time(),
            arbitration_id=can_id,
            data=payload,
            dlc=8,
            channel="can0",
            is_extended_id=True,
        )

        assert decoder.can_decode(frame) is True
        signals = decoder.decode(frame)

        assert len(signals) >= 1
        rpm_sig = next(s for s in signals if s.signal_name == "engine_rpm")
        assert rpm_sig.value == pytest.approx(852.5, rel=1e-4)
        assert rpm_sig.unit == "rpm"
        assert rpm_sig.quality.value == "valid"

    def test_decode_dual_value_map_frame(self):
        decoder = HefiProtocolDecoder()
        can_id = make_hefi_can_id(channel_index=2, ecu_serial=0x1A5)
        payload = pack_payload(42.5, 101.3)

        frame = RawCANFrame(
            timestamp=time.time(),
            arbitration_id=can_id,
            data=payload,
            dlc=8,
            channel="can0",
            is_extended_id=True,
        )

        signals = decoder.decode(frame)
        assert len(signals) == 2

        map_sig = next(s for s in signals if s.signal_name == "map_kpa")
        baro_sig = next(s for s in signals if s.signal_name == "baro_kpa")

        assert map_sig.value == pytest.approx(42.5, rel=1e-4)
        assert map_sig.unit == "kPa"
        assert baro_sig.value == pytest.approx(101.3, rel=1e-4)
        assert baro_sig.unit == "kPa"

    def test_unknown_channel_index_handled_safely(self):
        decoder = HefiProtocolDecoder()
        # Channel 999 is not in VERIFIED_CHANNELS
        can_id = make_hefi_can_id(channel_index=999, ecu_serial=0x1A5)
        payload = pack_payload(12.34, 56.78)

        frame = RawCANFrame(
            timestamp=time.time(),
            arbitration_id=can_id,
            data=payload,
            dlc=8,
            channel="can0",
            is_extended_id=True,
        )

        signals = decoder.decode(frame)
        assert len(signals) == 1
        assert "unverified" in signals[0].signal_name
        assert 999 in decoder.unknown_tracker.get_unknown_indices()

    def test_invalid_short_payload_ignored(self):
        decoder = HefiProtocolDecoder()
        can_id = make_hefi_can_id(channel_index=1, ecu_serial=0x1A5)

        # Truncated 4-byte payload
        frame = RawCANFrame(
            timestamp=time.time(),
            arbitration_id=can_id,
            data=b"\x00\x00\x00\x00",
            dlc=4,
            channel="can0",
            is_extended_id=True,
        )

        assert decoder.can_decode(frame) is False
        assert decoder.decode(frame) == []
