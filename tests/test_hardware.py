"""
Automated unit tests for the Hardware Abstraction Layer (HAL).
"""

import pytest
import asyncio

from app.can.frame import RawCANFrame
from app.hardware.interface import ConnectionState, ConnectionStatus, HardwareInterface
from app.hardware.simulator import SimulationScenario, VirtualSimulatorAdapter
from app.hardware.usb_can import UsbCanAdapter
from app.hardware.socketcan import SocketCanAdapter
from app.hardware.detection import discover_available_adapters


class TestHardwareInterfaceContract:
    def test_simulator_implements_protocol(self):
        adapter = VirtualSimulatorAdapter()
        assert isinstance(adapter, HardwareInterface)

    def test_usb_can_implements_protocol(self):
        adapter = UsbCanAdapter()
        assert isinstance(adapter, HardwareInterface)

    def test_socketcan_implements_protocol(self):
        adapter = SocketCanAdapter()
        assert isinstance(adapter, HardwareInterface)


class TestVirtualSimulatorLifecycle:
    def test_connect_and_disconnect(self):
        async def _run():
            adapter = VirtualSimulatorAdapter(channel_name="test_sim0")
            assert not adapter.is_connected()
            assert adapter.get_status().state == ConnectionState.DISCONNECTED

            # Connect
            connected = await adapter.connect()
            assert connected is True
            assert adapter.is_connected()
            assert adapter.get_status().state == ConnectionState.CONNECTED

            # Disconnect
            await adapter.disconnect()
            assert not adapter.is_connected()
            assert adapter.get_status().state == ConnectionState.DISCONNECTED

        asyncio.run(_run())

    def test_receive_frames_async(self):
        async def _run():
            adapter = VirtualSimulatorAdapter(broadcast_hz=50.0)
            await adapter.connect()

            # Wait briefly for frames to populate queue
            await asyncio.sleep(0.05)
            frame = await adapter.receive(timeout=0.5)

            assert frame is not None
            assert isinstance(frame, RawCANFrame)
            assert frame.is_extended_id is True
            assert len(frame.data) == 8

            status = adapter.get_status()
            assert status.frames_received >= 1
            assert status.bytes_received >= 8
            assert status.is_alive is True

            await adapter.disconnect()

        asyncio.run(_run())

    def test_reset_metrics(self):
        adapter = VirtualSimulatorAdapter()
        adapter._status.frames_received = 150
        adapter._status.error_frames = 2
        adapter._status.frames_dropped = 5
        adapter._status.bytes_received = 1200

        adapter.reset_metrics()
        status = adapter.get_status()
        assert status.frames_received == 0
        assert status.error_frames == 0
        assert status.frames_dropped == 0
        assert status.bytes_received == 0


class TestAdapterDiscovery:
    def test_discover_available_adapters(self):
        devices = discover_available_adapters()
        assert len(devices) >= 1
        sim_device = next((d for d in devices if d["adapter_type"] == "simulator"), None)
        assert sim_device is not None
        assert sim_device["available"] is True
