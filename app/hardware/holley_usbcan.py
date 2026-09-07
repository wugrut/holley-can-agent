"""
Native Holley USB-to-CAN hardware adapter interfacing via Windows WinUSB.

Directly communicates with the official Holley USB-to-CAN communication cable
(Part 558-443 or similar) using the pre-installed Holley USBCAN WinUSB driver.
No third-party hardware (PEAK, CANable) or external C-DLL dependencies required.
"""

from __future__ import annotations

import asyncio
import logging
import struct
import sys
import os
import threading
import time
from typing import List, NamedTuple, Optional

from app.can.frame import RawCANFrame
from app.hardware.interface import ConnectionState, ConnectionStatus, HardwareInterface

logger = logging.getLogger("efi.hardware.holley_usbcan")

# Device Interface GUID assigned to Holley USBCAN devices
# {abe07f2b-a951-4941-94a4-52adaa1fa53e}
HOLLEY_USBCAN_GUID_STR = "{abe07f2b-a951-4941-94a4-52adaa1fa53e}"

# Frame Protocol Constants
USBC_MAGIC: bytes = b"USBC"  # 0x55, 0x53, 0x42, 0x43
PACKET_SIZE: int = 20        # 4 header + 4 can_id + 1 dlc + 3 pad + 8 payload
BAUD_1M: int = 1_000_000     # 1 Mbps default for Holley HEFI CAN bus

# Win32 & WinUSB Constants
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
INVALID_HANDLE_VALUE = -1

# WinUSB Pipe Policies
PIPE_TRANSFER_TIMEOUT = 0x03
AUTO_FLUSH = 0x06
RAW_IO = 0x07

# SetupAPI flags
DIGCF_PRESENT = 0x00000002
DIGCF_DEVICEINTERFACE = 0x00000010


# Windows ctypes definitions (loaded conditionally for Windows platforms)
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", wintypes.BYTE * 8),
        ]

    HOLLEY_GUID = GUID(
        0xABE07F2B,
        0xA951,
        0x4941,
        (wintypes.BYTE * 8)(0x94, 0xA4, 0x52, 0xAD, 0xAA, 0x1F, 0xA5, 0x3E),
    )

    class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("InterfaceClassGuid", GUID),
            ("Flags", wintypes.DWORD),
            ("Reserved", ctypes.c_size_t),
        ]

    class USB_INTERFACE_DESCRIPTOR(ctypes.Structure):
        _fields_ = [
            ("bLength", wintypes.BYTE),
            ("bDescriptorType", wintypes.BYTE),
            ("bInterfaceNumber", wintypes.BYTE),
            ("bAlternateSetting", wintypes.BYTE),
            ("bNumEndpoints", wintypes.BYTE),
            ("bInterfaceClass", wintypes.BYTE),
            ("bInterfaceSubClass", wintypes.BYTE),
            ("bInterfaceProtocol", wintypes.BYTE),
            ("iInterface", wintypes.BYTE),
        ]

    class WINUSB_PIPE_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PipeType", ctypes.c_int),
            ("PipeId", wintypes.BYTE),
            ("MaximumPacketSize", wintypes.WORD),
            ("Interval", wintypes.BYTE),
        ]

    class WINUSB_SETUP_PACKET(ctypes.Structure):
        _fields_ = [
            ("RequestType", wintypes.BYTE),
            ("Request", wintypes.BYTE),
            ("Value", wintypes.WORD),
            ("Index", wintypes.WORD),
            ("Length", wintypes.WORD),
        ]

    class OVERLAPPED(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_ulong),
            ("InternalHigh", ctypes.c_ulong),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        ]

    # Bind SetupAPI
    try:
        setupapi = ctypes.windll.setupapi
        setupapi.SetupDiGetClassDevsW.argtypes = [
            ctypes.POINTER(GUID),
            wintypes.LPCWSTR,
            wintypes.HWND,
            wintypes.DWORD,
        ]
        setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE

        setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            ctypes.POINTER(GUID),
            wintypes.DWORD,
            ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
        ]
        setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL

        setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
        ]
        setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL

        setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]
        setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL
    except Exception as exc:
        logger.debug("Could not bind SetupAPI: %s", exc)

    # Bind Kernel32
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateEventW.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
    except Exception as exc:
        logger.debug("Could not bind Kernel32: %s", exc)

    # Bind WinUSB
    try:
        winusb = ctypes.windll.winusb
        winusb.WinUsb_Initialize.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.HANDLE)]
        winusb.WinUsb_Initialize.restype = wintypes.BOOL

        winusb.WinUsb_Free.argtypes = [wintypes.HANDLE]
        winusb.WinUsb_Free.restype = wintypes.BOOL

        winusb.WinUsb_QueryInterfaceSettings.argtypes = [
            wintypes.HANDLE,
            wintypes.BYTE,
            ctypes.POINTER(USB_INTERFACE_DESCRIPTOR),
        ]
        winusb.WinUsb_QueryInterfaceSettings.restype = wintypes.BOOL

        winusb.WinUsb_QueryPipe.argtypes = [
            wintypes.HANDLE,
            wintypes.BYTE,
            wintypes.BYTE,
            ctypes.POINTER(WINUSB_PIPE_INFORMATION),
        ]
        winusb.WinUsb_QueryPipe.restype = wintypes.BOOL

        winusb.WinUsb_SetPipePolicy.argtypes = [
            wintypes.HANDLE,
            wintypes.BYTE,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
        ]
        winusb.WinUsb_SetPipePolicy.restype = wintypes.BOOL

        winusb.WinUsb_ControlTransfer.argtypes = [
            wintypes.HANDLE,
            WINUSB_SETUP_PACKET,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
        ]
        winusb.WinUsb_ControlTransfer.restype = wintypes.BOOL

        winusb.WinUsb_ReadPipe.argtypes = [
            wintypes.HANDLE,
            wintypes.BYTE,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
        ]
        winusb.WinUsb_ReadPipe.restype = wintypes.BOOL

        winusb.WinUsb_WritePipe.argtypes = [
            wintypes.HANDLE,
            wintypes.BYTE,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
        ]
        winusb.WinUsb_WritePipe.restype = wintypes.BOOL

        winusb.WinUsb_GetOverlappedResult.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.BOOL,
        ]
        winusb.WinUsb_GetOverlappedResult.restype = wintypes.BOOL
    except Exception as exc:
        logger.debug("Could not bind WinUSB: %s", exc)


def enumerate_holley_devices(present_only: bool = True) -> List[str]:
    """
    Enumerate all connected Holley USBCAN device system paths.
    Returns list of device interface paths (e.g. \\\\?\\usb#vid_...#{abe07f2b-...}).
    """
    if sys.platform != "win32":
        return []

    flags = DIGCF_DEVICEINTERFACE
    if present_only:
        flags |= DIGCF_PRESENT

    hdev = setupapi.SetupDiGetClassDevsW(ctypes.byref(HOLLEY_GUID), None, None, flags)
    if not hdev or hdev in (-1, 0xFFFFFFFFFFFFFFFF, wintypes.HANDLE(INVALID_HANDLE_VALUE).value):
        return []

    paths: List[str] = []
    did = SP_DEVICE_INTERFACE_DATA()
    did.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
    index = 0

    try:
        while setupapi.SetupDiEnumDeviceInterfaces(
            hdev, None, ctypes.byref(HOLLEY_GUID), index, ctypes.byref(did)
        ):
            index += 1
            req_size = wintypes.DWORD(0)
            setupapi.SetupDiGetDeviceInterfaceDetailW(
                hdev, ctypes.byref(did), None, 0, ctypes.byref(req_size), None
            )
            if req_size.value == 0:
                continue

            buf = ctypes.create_string_buffer(req_size.value)
            # cbSize in SP_DEVICE_INTERFACE_DETAIL_DATA_W: 8 on x64, 6 on x86
            cb_size = 8 if struct.calcsize("P") == 8 else (4 + 2)
            struct.pack_into("<I", buf, 0, cb_size)

            if setupapi.SetupDiGetDeviceInterfaceDetailW(
                hdev, ctypes.byref(did), buf, req_size.value, None, None
            ):
                # DevicePath string begins at offset 4
                dev_path = ctypes.wstring_at(ctypes.addressof(buf) + 4)
                if dev_path:
                    paths.append(dev_path)
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(hdev)

    return paths


class ParsedHolleyPacket(NamedTuple):
    """
    Decoded representation of a 20-byte Holley USB-CAN bulk record.
    
    Fields:
        arbitration_id: Normalized CAN arbitration ID (29-bit or 11-bit).
        dlc: CAN Data Length Code (0 to 8).
        payload: Up to 8 bytes of CAN data payload.
        is_extended: True for 29-bit extended frame, False for 11-bit standard frame.
    """
    arbitration_id: int
    dlc: int
    payload: bytes
    is_extended: bool = True


def parse_holley_can_packet(packet: bytes) -> Optional[ParsedHolleyPacket]:
    """
    Parse a 20-byte Holley CAN packet from the USB stream.
    
    Byte layout verified from official Holley USBCAN-Driver.dll and Terminator X.exe:
      Bytes 0..3:   ASCII Magic b"USBC" (0x55, 0x53, 0x42, 0x43)
      Bytes 4..7:   Microcontroller CAN ID Word (uint32 LE):
                    - Bit 2: IDE (Identifier Extension flag, 1=29-bit Extended, 0=11-bit Standard)
                    - Bits 3..31: CAN Arbitration ID shifted left by 3 bits
                      * Extended (IDE=1): can_id = (raw_id_word >> 3) & 0x1FFFFFFF
                      * Standard (IDE=0): can_id = (raw_id_word >> 21) & 0x7FF (fallback (raw_id_word >> 3) & 0x7FF)
      Byte 8:       DLC (uint8, 0..8)
      Bytes 9..11:  Reserved/padding (3 bytes)
      Bytes 12..19: CAN Payload data (8 bytes)

    Returns:
        ParsedHolleyPacket if packet is structurally and semantically valid, else None.
    """
    if len(packet) != PACKET_SIZE or not packet.startswith(USBC_MAGIC):
        return None

    try:
        header, raw_id_word, dlc, pad, payload = struct.unpack("<4sIB3s8s", packet)
        if dlc > 8:
            return None

        is_extended = bool((raw_id_word >> 2) & 1)
        if is_extended:
            can_id = (raw_id_word >> 3) & 0x1FFFFFFF
            if can_id < 0 or can_id > 0x1FFFFFFF:
                return None
        else:
            can_id = (raw_id_word >> 21) & 0x7FF
            if can_id == 0:
                can_id = (raw_id_word >> 3) & 0x7FF
            if can_id < 0 or can_id > 0x7FF:
                return None

        return ParsedHolleyPacket(
            arbitration_id=can_id,
            dlc=dlc,
            payload=payload[:dlc],
            is_extended=is_extended,
        )
    except Exception:
        return None



class HolleyUsbCanAdapter(HardwareInterface):
    """
    Direct hardware adapter for the Holley USB-to-CAN communication cable.
    Communicates over WinUSB in passive listen-only mode.
    """

    def __init__(
        self,
        device_index: int = 0,
        bitrate: int = BAUD_1M,
        channel: str = "HOLLEY_USBCAN_0",
    ) -> None:
        self.device_index = device_index
        self.bitrate = bitrate
        self.channel = channel

        self._status = ConnectionStatus(
            state=ConnectionState.DISCONNECTED,
            adapter_name="HolleyUsbCanAdapter (WinUSB)",
            channel=channel,
            bitrate=bitrate,
        )

        # Device handles
        self._h_file: Optional[int] = None
        self._h_winusb: Optional[int] = None
        self._in_pipe_id: Optional[int] = None
        self._out_pipe_id: Optional[int] = None
        self._max_packet_size: int = 64

        # Streaming thread state
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._queue: Optional[asyncio.Queue[RawCANFrame]] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stream_buffer = bytearray()
        self._debug_raw_packets = os.environ.get("HOLLEY_DEBUG_RAW_PACKETS", "").strip() in ("1", "true", "TRUE")

    def is_connected(self) -> bool:
        return (
            self._h_winusb is not None
            and self._status.state in (ConnectionState.CONNECTED, ConnectionState.DEGRADED)
        )

    def get_status(self) -> ConnectionStatus:
        return self._status

    def reset_metrics(self) -> None:
        self._status.frames_received = 0
        self._status.error_frames = 0
        self._status.frames_dropped = 0
        self._status.bytes_received = 0

    async def connect(self) -> bool:
        """Enumerate, open, and configure the Holley USB-to-CAN dongle."""
        if sys.platform != "win32":
            self._status.state = ConnectionState.FAILED
            self._status.error_message = "Holley USBCAN cable is only supported on Windows."
            logger.error(self._status.error_message)
            return False

        self._status.state = ConnectionState.CONNECTING
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=10000)

        # Run connection synchronously in executor to avoid blocking loop
        success = await self._loop.run_in_executor(None, self._connect_sync)
        if success:
            self._status.state = ConnectionState.CONNECTED
            self._status.error_message = None
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._reader_worker,
                name="HolleyUsbCan-Reader",
                daemon=True,
            )
            self._thread.start()
            logger.info(
                "Connected to Holley USB-to-CAN Cable (WinUSB) at %d bps", self.bitrate
            )
            return True
        else:
            self._status.state = ConnectionState.FAILED
            return False

    def _connect_sync(self) -> bool:
        """Synchronous device opening and WinUSB initialization."""
        # 1. Enumerate devices
        paths = enumerate_holley_devices(present_only=True)
        if not paths:
            self._status.error_message = (
                "Holley USB cable not detected. Ensure cable is firmly plugged into USB."
            )
            logger.warning(self._status.error_message)
            return False

        if self.device_index >= len(paths):
            self._status.error_message = (
                f"Requested device index {self.device_index} exceeds available devices ({len(paths)} found)."
            )
            logger.warning(self._status.error_message)
            return False

        target_path = paths[self.device_index]
        logger.info("Found Holley device: %s", target_path)

        # 2. Open device file handle
        h_file = kernel32.CreateFileW(
            target_path,
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            FILE_FLAG_OVERLAPPED,
            None,
        )

        if not h_file or h_file in (-1, 0xFFFFFFFFFFFFFFFF, wintypes.HANDLE(INVALID_HANDLE_VALUE).value):
            err = kernel32.GetLastError()
            if err == 5:  # ERROR_ACCESS_DENIED
                self._status.error_message = (
                    "Device is in use by another application (e.g. Holley Terminator X software is open). "
                    "Please disconnect or close the Holley software to allow exclusive CAN bus access."
                )
            elif err == 32:  # ERROR_SHARING_VIOLATION
                self._status.error_message = (
                    "Sharing violation: Holley cable is locked by another process. Close Holley tuning software."
                )
            else:
                self._status.error_message = f"Failed to open device handle (Win32 Error: {err})"
            logger.error(self._status.error_message)
            return False

        self._h_file = h_file

        # 3. Initialize WinUSB interface
        h_winusb = wintypes.HANDLE()
        if not winusb.WinUsb_Initialize(h_file, ctypes.byref(h_winusb)):
            err = kernel32.GetLastError()
            self._status.error_message = f"WinUsb_Initialize failed (Win32 Error: {err})"
            logger.error(self._status.error_message)
            self._close_handles_sync()
            return False

        self._h_winusb = h_winusb.value

        # 4. Query interface and locate Bulk IN/OUT pipes
        iface_desc = USB_INTERFACE_DESCRIPTOR()
        if not winusb.WinUsb_QueryInterfaceSettings(h_winusb, 0, ctypes.byref(iface_desc)):
            err = kernel32.GetLastError()
            self._status.error_message = f"WinUsb_QueryInterfaceSettings failed (Win32 Error: {err})"
            logger.error(self._status.error_message)
            self._close_handles_sync()
            return False

        self._in_pipe_id = None
        self._out_pipe_id = None

        pipe_info = WINUSB_PIPE_INFORMATION()
        for i in range(iface_desc.bNumEndpoints):
            if winusb.WinUsb_QueryPipe(h_winusb, 0, i, ctypes.byref(pipe_info)):
                # PipeType 2 == UsbdPipeTypeBulk
                if pipe_info.PipeType == 2:
                    if pipe_info.PipeId & 0x80:
                        self._in_pipe_id = pipe_info.PipeId
                        self._max_packet_size = pipe_info.MaximumPacketSize or 64
                        logger.debug("Found Bulk IN pipe: 0x%02X (MaxPacket=%d)", self._in_pipe_id, self._max_packet_size)
                    else:
                        self._out_pipe_id = pipe_info.PipeId
                        logger.debug("Found Bulk OUT pipe: 0x%02X", self._out_pipe_id)

        if self._in_pipe_id is None:
            self._status.error_message = "Failed to locate Bulk IN endpoint on Holley device."
            logger.error(self._status.error_message)
            self._close_handles_sync()
            return False

        # 5. Set Pipe Policies: AUTO_FLUSH, RAW_IO, PIPE_TRANSFER_TIMEOUT (100 ms)
        true_val = wintypes.BYTE(1)
        timeout_ms = wintypes.DWORD(100)

        winusb.WinUsb_SetPipePolicy(h_winusb, self._in_pipe_id, AUTO_FLUSH, 1, ctypes.byref(true_val))
        winusb.WinUsb_SetPipePolicy(h_winusb, self._in_pipe_id, RAW_IO, 1, ctypes.byref(true_val))
        winusb.WinUsb_SetPipePolicy(h_winusb, self._in_pipe_id, PIPE_TRANSFER_TIMEOUT, 4, ctypes.byref(timeout_ms))

        # 6. Configure CAN Bitrate via Vendor Control Transfer (0x0222 command)
        setup = WINUSB_SETUP_PACKET(
            RequestType=0x40,  # Host-to-Device | Vendor | Device
            Request=0x00,
            Value=0x0222,      # Baud rate selection command (0x0222 in USBCAN-Driver.dll)
            Index=0x0000,
            Length=4,
        )
        rate_data = (ctypes.c_uint32)(self.bitrate)
        transferred = wintypes.DWORD(0)

        # Create manual-reset event for overlapped control transfer (matching CUsbCanDriver::SetSpeed)
        h_event = kernel32.CreateEventW(None, True, False, None)
        overlapped = OVERLAPPED()
        overlapped.hEvent = h_event

        res = winusb.WinUsb_ControlTransfer(
            h_winusb, setup, ctypes.byref(rate_data), 4, None, ctypes.byref(overlapped)
        )
        if not res:
            err = kernel32.GetLastError()
            if err == 997:  # ERROR_IO_PENDING
                wait_res = kernel32.WaitForSingleObject(h_event, 500)
                if wait_res == 0:  # WAIT_OBJECT_0
                    winusb.WinUsb_GetOverlappedResult(
                        h_winusb, ctypes.byref(overlapped), ctypes.byref(transferred), False
                    )
                else:
                    err = kernel32.GetLastError()

            # Characterize error 121 (ERROR_SEM_TIMEOUT) or non-zero error:
            if err == 121:
                logger.info(
                    "Holley adapter bitrate control transfer timed out (Win32 Error 121: ERROR_SEM_TIMEOUT). "
                    "Hardware operates at factory default 1,000,000 bps."
                )
            elif err not in (0, 997):
                logger.warning(
                    "WinUsb_ControlTransfer for bitrate returned Win32 error %d. "
                    "Continuing at hardware default bitrate (1,000,000 bps).",
                    err,
                )
        if h_event:
            kernel32.CloseHandle(h_event)

        return True

    def _reader_worker(self) -> None:
        """Background worker thread continuously reading Bulk IN frames."""
        buf_size = max(512, self._max_packet_size * 8)
        read_buf = ctypes.create_string_buffer(buf_size)
        bytes_transferred = wintypes.DWORD(0)

        self._status.reader_alive = True
        logger.debug("HolleyUsbCan reader worker started.")
        try:
            while not self._stop_event.is_set():
                if not self._h_winusb or self._in_pipe_id is None:
                    break

                success = winusb.WinUsb_ReadPipe(
                    self._h_winusb,
                    self._in_pipe_id,
                    read_buf,
                    buf_size,
                    ctypes.byref(bytes_transferred),
                    None,
                )

                if success and bytes_transferred.value > 0:
                    chunk = read_buf.raw[: bytes_transferred.value]
                    self._status.bytes_received += len(chunk)
                    try:
                        self._process_stream_chunk(chunk)
                    except Exception as chunk_err:
                        logger.warning("Error processing stream chunk: %s", chunk_err)
                else:
                    err = kernel32.GetLastError()
                    # Error 1167 (ERROR_DEVICE_NOT_CONNECTED) or 121 (ERROR_SEM_TIMEOUT)
                    if err == 1167:  # Device unplugged
                        logger.warning("Holley USB cable was disconnected.")
                        self._status.state = ConnectionState.RECONNECTING
                        self._status.error_message = "USB cable was unplugged."
                        break
                    elif err == 121:  # Semaphore timeout (normal idle on quiet bus)
                        continue
                    else:
                        # Brief sleep to avoid spinning on unexpected transient error
                        time.sleep(0.01)
        finally:
            self._status.reader_alive = False
            logger.debug("HolleyUsbCan reader worker exiting.")

    def _process_stream_chunk(self, chunk: bytes) -> None:
        """Appends chunk to buffer, synchronizes to USBC magic, and dispatches frames."""
        self._stream_buffer.extend(chunk)

        while True:
            idx = self._stream_buffer.find(USBC_MAGIC)
            if idx == -1:
                # No magic found: discard all but last 3 bytes in case magic is split across chunks
                if len(self._stream_buffer) > 3:
                    self._stream_buffer = bytearray(self._stream_buffer[-3:])
                break

            if idx > 0:
                # Discard desynchronized leading noise
                del self._stream_buffer[:idx]

            if len(self._stream_buffer) < PACKET_SIZE:
                # Incomplete packet, await more bytes
                break

            packet = bytes(self._stream_buffer[:PACKET_SIZE])
            del self._stream_buffer[:PACKET_SIZE]
            self._status.raw_packets_seen += 1

            if self._debug_raw_packets:
                logger.info(
                    "RAW USB PACKET (%d bytes): %s",
                    len(packet),
                    " ".join(f"{b:02X}" for b in packet),
                )

            parsed = parse_holley_can_packet(packet)
            if parsed is not None:
                can_id = parsed.arbitration_id
                dlc = parsed.dlc
                payload = parsed.payload
                is_extended = parsed.is_extended

                if self._debug_raw_packets:
                    logger.info(
                        "  -> Decoded Frame: CAN_ID=0x%08X (extended=%s) DLC=%d Payload=%s",
                        can_id,
                        is_extended,
                        dlc,
                        " ".join(f"{b:02X}" for b in payload),
                    )

                try:
                    frame = RawCANFrame(
                        timestamp=time.time(),
                        arbitration_id=can_id,
                        data=payload,
                        dlc=dlc,
                        channel=self.channel,
                        is_extended_id=is_extended,
                        is_error_frame=False,
                    )
                    self._status.frames_received += 1
                    self._status.last_frame_time = frame.timestamp

                    if self._queue is not None and self._loop is not None:
                        try:
                            self._loop.call_soon_threadsafe(self._enqueue_frame, frame)
                        except RuntimeError:
                            pass
                except Exception as frame_err:
                    logger.warning("Error creating RawCANFrame: %s", frame_err)
                    self._status.malformed_packets += 1
            else:
                self._status.malformed_packets += 1
                logger.warning(
                    "Discarded malformed CAN packet: raw=%s",
                    " ".join(f"{b:02X}" for b in packet),
                )

    def _enqueue_frame(self, frame: RawCANFrame) -> None:
        """Helper to enqueue frame from thread-safe callback."""
        if self._queue is not None:
            try:
                self._queue.put_nowait(frame)
            except asyncio.QueueFull:
                self._status.frames_dropped += 1

    async def receive(self, timeout: float = 1.0) -> Optional[RawCANFrame]:
        """
        Receive single CAN message asynchronously without blocking the event loop.
        """
        if not self.is_connected() or self._queue is None:
            return None

        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def _close_handles_sync(self) -> None:
        """Closes WinUSB and file handles synchronously."""
        if self._h_winusb:
            try:
                winusb.WinUsb_Free(self._h_winusb)
            except Exception as exc:
                logger.debug("WinUsb_Free error: %s", exc)
            self._h_winusb = None

        if self._h_file and self._h_file != -1:
            try:
                kernel32.CloseHandle(self._h_file)
            except Exception as exc:
                logger.debug("CloseHandle error: %s", exc)
            self._h_file = None

    async def disconnect(self) -> None:
        """Gracefully shut down reader thread and close device."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            await asyncio.get_running_loop().run_in_executor(
                None, self._thread.join, 1.0
            )
            self._thread = None

        if self._loop:
            await self._loop.run_in_executor(None, self._close_handles_sync)
        else:
            self._close_handles_sync()

        self._status.state = ConnectionState.DISCONNECTED
        logger.info("Disconnected from Holley USB-to-CAN Cable.")

    def send(self, frame: RawCANFrame) -> bool:
        """
        Passive safety invariant: Transmissions are strictly disabled on vehicle bus.
        HolleyUsbCanAdapter operates strictly in passive listen-only mode.
        """
        logger.warning(
            "CAN transmission rejected: HolleyUsbCanAdapter is strictly passive/listen-only."
        )
        return False
