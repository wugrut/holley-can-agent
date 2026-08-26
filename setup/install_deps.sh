#!/usr/bin/env bash
# =============================================================================
# install_deps.sh — Install all dependencies on CachyOS / Arch Linux
# =============================================================================
set -euo pipefail

echo "═══════════════════════════════════════════════════"
echo "  Holley CAN Agent — Dependency Installation"
echo "═══════════════════════════════════════════════════"

# ── System packages ─────────────────────────────────────────────────────────
echo ""
echo "[1/3] Installing system packages..."
sudo pacman -S --needed --noconfirm \
    can-utils \
    python \
    python-pip \
    python-virtualenv \
    iproute2

echo "  ✓ System packages installed"

# ── Python virtual environment ──────────────────────────────────────────────
echo ""
echo "[2/3] Setting up Python virtual environment..."

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="${PROJECT_DIR}/.venv"

if [ ! -d "$VENV_DIR" ]; then
    python -m venv "$VENV_DIR"
    echo "  ✓ Created venv at ${VENV_DIR}"
else
    echo "  ✓ Venv already exists at ${VENV_DIR}"
fi

source "${VENV_DIR}/bin/activate"

# ── Python packages ────────────────────────────────────────────────────────
echo ""
echo "[3/3] Installing Python packages..."
pip install --upgrade pip
pip install -r "${PROJECT_DIR}/requirements.txt"

echo "  ✓ Python packages installed"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✓ All dependencies installed."
echo "  Activate the venv:  source ${VENV_DIR}/bin/activate"
echo "═══════════════════════════════════════════════════"
