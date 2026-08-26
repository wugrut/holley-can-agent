# Holley CAN Agent

**Agentic ECU monitoring workstation for the Holley Terminator X Max**

A headless Python middleware that passively ingests the Holley HEFI 3rd-Party CAN Communications Protocol, stores time-series data, serves a real-time web dashboard, and exposes an agent-queryable API for conversational analysis.

Designed to run on a GMKtec EVO-X2 mini PC with CachyOS/Arch Linux, connected to the ECU via PCAN-USB adapter.

---

## Architecture

```
ECU (J3 CAN) → CAN Splitter → PCAN-USB → SocketCAN (can0)
                                              ↓
                                    Python Middleware
                                    ├── Protocol Decoder (HEFI)
                                    ├── SQLite Time-Series DB
                                    ├── Alert Engine
                                    ├── FastAPI REST + WebSocket
                                    └── Web Dashboard (:8420)
```

## Features

- **Live Dashboard** — Real-time canvas gauges (RPM, MAP/Boost, AFR, Timing, Coolant, Battery, TPS, Gear) accessible from any device on WiFi
- **HEFI Protocol Decoder** — Decodes 29-bit extended CAN IDs with automatic ECU serial detection
- **Anomaly Detection** — Lean/rich AFR, timing retard (knock), overboost, low voltage, high coolant, sensor dropout
- **Time-Series Storage** — SQLite with WAL mode, configurable downsample rate, 90-day retention
- **Agent Tools** — High-level Python functions for LLM-based agents (live snapshot, history queries, WOT analysis, transmission status)
- **REST API** — Full HTTP API for programmatic access

## Quick Start

### 1. Hardware Setup

1. Connect the CAN splitter to the Terminator X Max **J3 connector** (3rd-party CAN bus)
2. Ensure **120Ω termination** at both ends of the CAN bus
3. Plug the **PCAN-USB adapter** into the GMKtec EVO-X2

### 2. Software Setup

```bash
# Clone the project
git clone <your-repo> /opt/holley-can-agent
cd /opt/holley-can-agent

# Install dependencies
chmod +x setup/*.sh
./setup/install_deps.sh

# Initialize SocketCAN
./setup/socketcan_init.sh

# Verify CAN traffic (with engine running or key-on)
candump can0
```

### 3. Run

```bash
# Activate virtual environment
source .venv/bin/activate

# Start the agent
python main.py
```

The dashboard will be available at `http://<evo-x2-ip>:8420`

### 4. Auto-Start on Boot (optional)

```bash
# Create the holley user
sudo useradd -r -s /usr/sbin/nologin holley

# Install the systemd service
sudo cp setup/holley-can-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable holley-can-agent
sudo systemctl start holley-can-agent
```

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Web dashboard |
| GET | `/api/live` | All channels snapshot |
| GET | `/api/live/{channel}` | Single channel value |
| GET | `/api/history?channel=rpm&start=...&end=...` | Historical data |
| GET | `/api/alerts` | Active/recent alerts |
| GET | `/api/discovery` | Discovered CAN IDs |
| GET | `/api/health` | System health |
| WS | `/ws` | WebSocket live stream |

## Configuration

Edit `config.yaml` to customize:

- CAN interface and bitrate
- ECU serial number (or auto-detect)
- Alert thresholds
- Storage sample rate and retention
- API host and port
- Dashboard gauge ranges

## HEFI Protocol Notes

The Holley HEFI 3rd-Party CAN protocol uses **29-bit extended CAN IDs** at **1 Mbit/s**:

- **CAN ID** = `Base ID + (ECU Serial & 0x7FF)`
- **Mask** `0xFFFFF800` to strip the serial and isolate the channel index
- **Payload**: 8 bytes = two 32-bit big-endian IEEE 754 floats
- The ECU serial number is printed on the back of the unit

## License

MIT
