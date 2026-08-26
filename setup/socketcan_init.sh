#!/usr/bin/env bash
# =============================================================================
# socketcan_init.sh — Initialize PCAN-USB adapter via SocketCAN
# Target: CachyOS / Arch Linux on GMKtec EVO-X2
# =============================================================================
set -euo pipefail

CAN_IF="${CAN_INTERFACE:-can0}"
BITRATE="${CAN_BITRATE:-1000000}"  # 1 Mbit/s per HEFI spec

echo "═══════════════════════════════════════════════════"
echo "  Holley CAN Agent — SocketCAN Initialization"
echo "═══════════════════════════════════════════════════"

# ── Step 1: Load the PCAN-USB kernel module ──────────────────────────────────
echo ""
echo "[1/4] Loading peak_usb kernel module..."
if lsmod | grep -q peak_usb; then
    echo "  ✓ peak_usb already loaded"
else
    sudo modprobe peak_usb
    if lsmod | grep -q peak_usb; then
        echo "  ✓ peak_usb loaded successfully"
    else
        echo "  ✗ Failed to load peak_usb module"
        echo "    Check: grep CONFIG_CAN_PEAK_USB /boot/config-\$(uname -r)"
        echo "    You may need to install the linux-headers package:"
        echo "      sudo pacman -S linux-headers"
        exit 1
    fi
fi

# ── Step 2: Verify hardware detection ───────────────────────────────────────
echo ""
echo "[2/4] Checking for PCAN-USB hardware..."
if lsusb | grep -qi "0c72"; then
    echo "  ✓ Peak Systems USB device detected"
    lsusb | grep -i "0c72" | sed 's/^/    /'
else
    echo "  ✗ No Peak Systems USB device found"
    echo "    Ensure the PCAN-USB adapter is plugged in"
    exit 1
fi

# ── Step 3: Configure CAN interface ─────────────────────────────────────────
echo ""
echo "[3/4] Configuring ${CAN_IF} at ${BITRATE} bit/s..."

# Bring down first if already up (safe to fail)
sudo ip link set "${CAN_IF}" down 2>/dev/null || true

# Set CAN parameters
sudo ip link set "${CAN_IF}" type can \
    bitrate "${BITRATE}" \
    restart-ms 100 \
    berr-reporting on

# Bring up the interface
sudo ip link set "${CAN_IF}" up

echo "  ✓ ${CAN_IF} configured and UP"

# ── Step 4: Verify ──────────────────────────────────────────────────────────
echo ""
echo "[4/4] Interface status:"
echo "───────────────────────────────────────────────────"
ip -details -statistics link show "${CAN_IF}"
echo "───────────────────────────────────────────────────"

echo ""
echo "✓ SocketCAN ready. Test with:  candump ${CAN_IF}"
echo ""
