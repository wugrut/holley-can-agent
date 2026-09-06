# Cybersecurity & Safety Architecture Specification

**System:** EFI Intelligence Copilot  
**Status:** Active  
**Last Updated:** September 2026

---

## 1. Threat Model & Security Boundaries

Operating in an automotive and motorsport environment presents distinct physical, electrical, and cybersecurity challenges. EFI Intelligence Copilot treats **all CAN bus frames, USB hardware inputs, and network requests as untrusted**.

```
[ UNTRUSTED PHYSICAL CAN BUS ]
   │
   ▼
[ HARDWARE & PAYLOAD SANITIZER ]
   │  - Validate 29-bit ID Range (0 .. 0x1FFFFFFF)
   │  - Enforce DLC == 8 bytes
   │  - Strip NaN / +/-Inf from IEEE 754 floats
   │  - Strict Read-Only Socket Configuration
   ▼
[ SECURE TELEMETRY BUFFER ]
   │
   ▼
[ ZERO-WRITE APPLICATION CORE ]
   │
   ├── [ REST / WebSocket Server ] (Localhost / LAN Only)
   └── [ AI Gateway ] (Deterministic Tools Only)
```

---

## 2. Mandatory Security Enforcements

### 2.1 Zero-Write Architectural Lock
* **No CAN Transmission Logic:** The application's core hardware interfaces operate in **Listen-Only / Passive Mode** wherever supported by the physical adapter (e.g. SocketCAN `listen-only on`, PCAN `PCAN_CHANNEL_RECEIVE_ONLY`).
* **No Firmware Flashing:** The software does not implement, link, or invoke Holley proprietary calibration upload/download routines.
* **Autonomous Safety:** Under no circumstances will any AI model, diagnostic rule, or background thread attempt to alter ignition advance, fuel pulse width, rev limiters, or boost targets.

### 2.2 Untrusted CAN Frame Validation
* **Arbitration ID Validation:** Discards any frame whose arbitration ID exceeds 29-bit boundary ($> \text{0x1FFFFFFF}$).
* **DLC Enforcement:** Only frames with $\text{DLC} = 8$ are passed to the payload unpacker. Truncated or oversized frames are routed to the error logger.
* **Floating-Point Sanitization:** Floats are verified with `math.isnan()` and `math.isinf()` before passing to storage or mathematical algorithms. Corrupted floats are discarded with `SignalQuality.INVALID`.

### 2.3 Network & API Security
* **Network Binding:** By default, the embedded REST and WebSocket server binds to `127.0.0.1`. Binding to `0.0.0.0` (for in-car WiFi tablet displays) requires explicit user configuration.
* **No Remote Execution:** The API provides read-only endpoints for telemetry, history, and diagnostics. No endpoints exist that allow arbitrary command execution or shell access.
* **CORS Restrictions:** Configurable CORS origins preventing cross-origin script execution from untrusted browser sessions.

### 2.4 Privacy & Logging Integrity
* **Secret Masking:** AI provider API keys (Gemini, Anthropic, OpenAI) are strictly read from environment variables and never logged or serialized into SQLite session files.
* **Audit Logging:** All AI requests and structured tool inputs are logged locally with timestamps, ensuring full reproducibility and auditability of AI recommendations.
