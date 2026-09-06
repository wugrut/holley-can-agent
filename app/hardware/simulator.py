"""
Virtual telemetry simulator generating deterministic Holley HEFI CAN frames.
"""

from __future__ import annotations

import asyncio
import math
import random
import struct
import time
from collections import deque
from enum import Enum
from typing import Optional

from app.can.frame import RawCANFrame
from app.hardware.interface import ConnectionState, ConnectionStatus, HardwareInterface


class SimulationScenario(str, Enum):
    """Deterministic simulation profiles for development and automated testing."""
    IDLE_STABLE = "idle_stable"
    IDLE_UNSTABLE = "idle_unstable"         # RPM hunting / oscillation
    CRUISE_NORMAL = "cruise_normal"
    CRUISE_RICH_DRIFT = "cruise_rich_drift" # Closed loop learning negative drift
    WOT_PULL_NORMAL = "wot_pull_normal"     # Clean acceleration to redline
    WOT_PULL_LEAN_DEV = "wot_pull_lean_dev" # Lean deviation (+8% learn under high load)
    THERMAL_EVENT = "thermal_event"         # Coolant overheating
    LOW_VOLTAGE = "low_voltage"             # Battery sinking under load
    SENSOR_DROPOUT = "sensor_dropout"       # TPS/MAP drops out
    MULTI_CYCLE = "multi_cycle"             # Continuous driving state cycle


def make_hefi_can_id(channel_index: int, ecu_serial: int = 0x1A5) -> int:
    """
    Construct a 29-bit HEFI broadcast CAN ID.

    Bit layout:
      28:    1 (Command/Broadcast)
      27:25: 111 (Broadcast target)
      24:14: Channel Index (11 bits)
      13:11: 010 (ECU source)
      10:0:  ECU Serial lower 11 bits
    """
    can_id = (1 << 28)
    can_id |= (0b111 << 25)
    can_id |= ((channel_index & 0x7FF) << 14)
    can_id |= (0b010 << 11)
    can_id |= (ecu_serial & 0x7FF)
    return can_id


def pack_payload(value_a: float, value_b: float = 0.0) -> bytes:
    """Pack two 32-bit floats into big-endian IEEE 754 payload."""
    return struct.pack(">ff", float(value_a), float(value_b))


class VirtualSimulatorAdapter(HardwareInterface):
    """
    In-memory virtual hardware adapter capable of generating deterministic CAN streams.
    Implements the complete HardwareInterface contract.
    """

    def __init__(
        self,
        scenario: SimulationScenario = SimulationScenario.MULTI_CYCLE,
        ecu_serial: int = 0x1A5,
        broadcast_hz: float = 20.0,
        channel_name: str = "sim_virtual0",
    ) -> None:
        self.scenario = scenario
        self.ecu_serial = ecu_serial
        self.broadcast_hz = broadcast_hz
        self.channel_name = channel_name

        self._status = ConnectionStatus(
            state=ConnectionState.DISCONNECTED,
            adapter_name="VirtualSimulatorAdapter",
            channel=channel_name,
            bitrate=1_000_000,
        )

        self._frame_queue: deque[RawCANFrame] = deque(maxlen=2000)
        self._is_running = False
        self._sim_task: Optional[asyncio.Task] = None
        self._sim_time = 0.0
        self._lock = asyncio.Lock()

        # Engine internal state variables
        self.rpm = 850.0
        self.map_kpa = 35.0
        self.baro_kpa = 101.3
        self.tps = 0.0
        self.coolant_temp = 185.0
        self.iat = 85.0
        self.target_afr = 14.7
        self.afr_measured = 14.7
        self.fuel_learn = 0.0
        self.battery_voltage = 14.2
        self.fuel_pw = 2.1
        self.ignition_timing = 18.0
        self.trans_gear = 0
        self.trans_temp = 165.0
        self.oil_pressure = 45.0
        self.fuel_pressure = 58.0
        self.vehicle_speed = 0.0

    async def connect(self) -> bool:
        """Connect the virtual simulator and start asynchronous frame generator."""
        if self._is_running:
            return True

        self._status.state = ConnectionState.CONNECTING
        await asyncio.sleep(0.01)  # Simulate hardware handshake
        self._is_running = True
        self._status.state = ConnectionState.CONNECTED
        self._status.error_message = None

        # Start generator loop in background
        self._sim_task = asyncio.create_task(self._generator_loop())
        return True

    async def disconnect(self) -> None:
        """Stop simulator and drain buffers."""
        self._is_running = False
        if self._sim_task and not self._sim_task.done():
            self._sim_task.cancel()
            try:
                await self._sim_task
            except asyncio.CancelledError:
                pass
        self._status.state = ConnectionState.DISCONNECTED

    def is_connected(self) -> bool:
        return self._is_running and self._status.state == ConnectionState.CONNECTED

    def get_status(self) -> ConnectionStatus:
        return self._status

    def reset_metrics(self) -> None:
        self._status.frames_received = 0
        self._status.error_frames = 0
        self._status.frames_dropped = 0
        self._status.bytes_received = 0

    def set_scenario(self, scenario: SimulationScenario) -> None:
        """Dynamically switch scenario mode."""
        self.scenario = scenario
        self._sim_time = 0.0

    async def receive(self, timeout: float = 1.0) -> Optional[RawCANFrame]:
        """Receive the next generated frame from queue."""
        if not self.is_connected():
            return None

        start = time.time()
        while time.time() - start < timeout:
            if self._frame_queue:
                frame = self._frame_queue.popleft()
                self._status.frames_received += 1
                self._status.bytes_received += len(frame.data)
                self._status.last_frame_time = time.time()
                return frame
            await asyncio.sleep(0.002)

        return None

    def step_deterministic(self, dt: float = 0.05) -> list[RawCANFrame]:
        """
        Synchronous step for deterministic unit testing without async delays.
        Generates and returns all CAN frames for the timestep.
        """
        self._sim_time += dt
        self._update_engine_state(self._sim_time)
        return self._generate_telemetry_burst(time.time())

    async def _generator_loop(self) -> None:
        """Background coroutine generating continuous CAN frames at broadcast_hz."""
        interval = 1.0 / self.broadcast_hz
        try:
            while self._is_running:
                now = time.time()
                self._sim_time += interval
                self._update_engine_state(self._sim_time)
                frames = self._generate_telemetry_burst(now)

                for frame in frames:
                    if len(self._frame_queue) >= self._frame_queue.maxlen:
                        self._status.frames_dropped += 1
                    else:
                        self._frame_queue.append(frame)

                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass

    def _update_engine_state(self, t: float) -> None:
        """Calculate state variables based on current scenario and time."""
        sc = self.scenario

        if sc == SimulationScenario.IDLE_STABLE:
            self.rpm = 850.0 + random.uniform(-15.0, 15.0)
            self.tps = 0.0
            self.map_kpa = 36.0 + random.uniform(-0.5, 0.5)
            self.target_afr = 14.7
            self.afr_measured = 14.7 + random.uniform(-0.15, 0.15)
            self.fuel_learn = random.uniform(-1.0, 1.0)
            self.battery_voltage = 14.2 + random.uniform(-0.05, 0.05)
            self.coolant_temp = 185.0
            self.trans_gear = 0

        elif sc == SimulationScenario.IDLE_UNSTABLE:
            # Hunting idle with 1.0 Hz sinusoidal surge
            osc = math.sin(t * 2.0 * math.pi * 0.9)
            self.rpm = 850.0 + osc * 240.0 + random.uniform(-20, 20)
            self.tps = 0.0
            self.map_kpa = 38.0 + osc * 12.0
            self.target_afr = 14.7
            self.afr_measured = 14.7 + osc * 0.9 + random.uniform(-0.1, 0.1)
            self.fuel_learn = osc * 4.0
            self.coolant_temp = 190.0
            self.trans_gear = 0

        elif sc == SimulationScenario.CRUISE_NORMAL:
            self.rpm = 2200.0 + random.uniform(-20, 20)
            self.tps = 18.0 + random.uniform(-0.5, 0.5)
            self.map_kpa = 48.0 + random.uniform(-1.0, 1.0)
            self.target_afr = 14.7
            self.afr_measured = 14.7 + random.uniform(-0.2, 0.2)
            self.fuel_learn = random.uniform(-1.5, 1.5)
            self.trans_gear = 4
            self.vehicle_speed = 65.0

        elif sc == SimulationScenario.CRUISE_RICH_DRIFT:
            # Fuel learn progressively drifting rich (-14%)
            drift = max(-14.0, -0.5 * t)
            self.rpm = 2200.0 + random.uniform(-20, 20)
            self.tps = 18.0
            self.map_kpa = 48.0
            self.target_afr = 14.7
            self.afr_measured = 14.1 + random.uniform(-0.1, 0.1)
            self.fuel_learn = drift
            self.trans_gear = 4

        elif sc == SimulationScenario.WOT_PULL_NORMAL:
            # Progressive acceleration from 2500 to 6500 RPM over 5 seconds
            phase = (t % 8.0)
            if phase < 5.0:
                frac = phase / 5.0
                self.rpm = 2500.0 + frac * 4000.0
                self.tps = 100.0
                self.map_kpa = 98.0 + random.uniform(-0.5, 0.5)
                self.target_afr = 12.6
                self.afr_measured = 12.6 + random.uniform(-0.1, 0.1)
                self.fuel_learn = random.uniform(-0.5, 0.5)
                self.trans_gear = 3
            else:
                self.rpm = 1200.0
                self.tps = 0.0
                self.map_kpa = 28.0
                self.target_afr = 14.7
                self.afr_measured = 15.5  # Overrun fuel cut lean

        elif sc == SimulationScenario.WOT_PULL_LEAN_DEV:
            # High load pull where fuel learn reaches +8.5%
            phase = (t % 8.0)
            if phase < 5.0:
                frac = phase / 5.0
                self.rpm = 2800.0 + frac * 3500.0
                self.tps = 100.0
                self.map_kpa = 97.5 + random.uniform(-0.5, 0.5)
                self.target_afr = 12.5
                self.afr_measured = 12.6 + random.uniform(-0.1, 0.1)
                self.fuel_learn = 8.2 + random.uniform(-0.4, 0.4)
                self.trans_gear = 3
            else:
                self.rpm = 1100.0
                self.tps = 0.0
                self.map_kpa = 28.0
                self.fuel_learn = 1.0

        elif sc == SimulationScenario.THERMAL_EVENT:
            # Coolant climbing past 235 F
            self.rpm = 850.0
            self.tps = 0.0
            self.coolant_temp = min(245.0, 185.0 + t * 2.5)

        elif sc == SimulationScenario.LOW_VOLTAGE:
            # Battery voltage drops to 11.2V
            self.rpm = 2500.0
            self.battery_voltage = max(11.2, 14.2 - t * 0.4)

        elif sc == SimulationScenario.SENSOR_DROPOUT:
            # MAP / TPS drops to zero after 2 seconds
            self.rpm = 2000.0
            if t > 2.0:
                self.tps = 0.0
                self.map_kpa = 0.0  # Dropout
            else:
                self.tps = 25.0
                self.map_kpa = 52.0

        elif sc == SimulationScenario.MULTI_CYCLE:
            # Continuous cycle: Idle (5s) -> Accel (5s) -> Cruise (10s) -> WOT (4s) -> Decel (6s)
            cycle = t % 30.0
            if cycle < 5.0:
                self.rpm = 850.0 + random.uniform(-10, 10)
                self.tps = 0.0
                self.map_kpa = 36.0
                self.target_afr = 14.7
                self.afr_measured = 14.7 + random.uniform(-0.1, 0.1)
                self.fuel_learn = 0.0
                self.trans_gear = 0
            elif cycle < 10.0:
                p = (cycle - 5.0) / 5.0
                self.rpm = 1000.0 + p * 2000.0
                self.tps = 30.0
                self.map_kpa = 60.0
                self.target_afr = 14.2
                self.afr_measured = 14.2
                self.fuel_learn = 1.2
                self.trans_gear = 2
            elif cycle < 20.0:
                self.rpm = 2200.0
                self.tps = 18.0
                self.map_kpa = 45.0
                self.target_afr = 14.7
                self.afr_measured = 14.7
                self.fuel_learn = 0.5
                self.trans_gear = 4
            elif cycle < 24.0:
                p = (cycle - 20.0) / 4.0
                self.rpm = 3000.0 + p * 3200.0
                self.tps = 100.0
                self.map_kpa = 98.0
                self.target_afr = 12.5
                self.afr_measured = 12.5
                self.fuel_learn = 7.8
                self.trans_gear = 3
            else:
                self.rpm = 1200.0
                self.tps = 0.0
                self.map_kpa = 26.0
                self.target_afr = 14.7
                self.afr_measured = 16.0
                self.fuel_learn = 0.0
                self.trans_gear = 4

    def _generate_telemetry_burst(self, timestamp: float) -> list[RawCANFrame]:
        """Generate full burst of HEFI broadcast frames for all active channels."""
        frames: list[RawCANFrame] = []

        def add_frame(channel_index: int, val_a: float, val_b: float = 0.0) -> None:
            can_id = make_hefi_can_id(channel_index, self.ecu_serial)
            data = pack_payload(val_a, val_b)
            frames.append(
                RawCANFrame(
                    timestamp=timestamp,
                    arbitration_id=can_id,
                    data=data,
                    dlc=8,
                    channel=self.channel_name,
                    is_extended_id=True,
                )
            )

        # 1: RPM
        add_frame(1, self.rpm, 0.0)
        # 2: MAP / Baro
        add_frame(2, self.map_kpa, self.baro_kpa)
        # 3: TPS
        add_frame(3, self.tps, 0.0)
        # 4: Coolant Temp
        add_frame(4, self.coolant_temp, 0.0)
        # 5: Target AFR
        add_frame(5, self.target_afr, 0.0)
        # 6: AFR Bank 1
        add_frame(6, self.afr_measured, 1.0)
        # 8: AFR Avg
        add_frame(8, self.afr_measured, 0.0)
        # 11: Ignition Timing
        add_frame(11, self.ignition_timing, 0.0)
        # 12: Battery Voltage
        add_frame(12, self.battery_voltage, 0.0)
        # 13: Fuel Learn
        add_frame(13, self.fuel_learn, 0.0)
        # 14: Closed Loop Flag (1.0 = active)
        add_frame(14, 1.0 if self.rpm > 400 else 0.0, 0.0)
        # 15: IAT
        add_frame(15, self.iat, 0.0)
        # 16: Fuel Pulse Width / Duty Cycle
        duty = (self.rpm * self.fuel_pw) / 1200.0
        add_frame(16, self.fuel_pw, min(100.0, duty))
        # 18: Target Idle
        add_frame(18, 850.0, 25.0)
        # 20: Transmission Gear
        add_frame(20, float(self.trans_gear), float(self.trans_gear))
        # 21: Trans Temp
        add_frame(21, self.trans_temp, 0.0)
        # 30: Oil Pressure
        add_frame(30, self.oil_pressure, 0.0)
        # 31: Fuel Pressure
        add_frame(31, self.fuel_pressure, 0.0)
        # 32: Vehicle Speed
        add_frame(32, self.vehicle_speed, 0.0)

        return frames
