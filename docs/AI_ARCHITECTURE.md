# AI Architecture & Reasoning Layer Specification

**System:** EFI Intelligence Copilot  
**Tier:** AI Reasoning & Natural Language Interface  
**Status:** In Development  
**Last Updated:** September 2026

---

## 1. Safety & Isolation Barrier

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          PHYSICAL CONTROL BOUNDARY                      │
│                                                                         │
│   CAN BUS ◄────► [ HAL / Transports ] ◄────► [ ECU Calibration ]        │
│                               ▲                                         │
│                               │ HARDWARE FIREWALL: ZERO LLM ACCESS      │
│                               ▼                                         │
│                    [ Deterministic Engine ]                             │
│                  - Event Detection (Python)                             │
│                  - Baseline Statistics (NumPy)                          │
│                  - Rule-Based Diagnostics (Python)                      │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ Structured JSON Data Only
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      AI REASONING & INTERPRETATION                      │
│                                                                         │
│   [ Agnostic LLM Gateway ] (Gemini, Claude, OpenAI, Local Ollama)       │
│                               ▲                                         │
│                               ▼                                         │
│                 [ Deterministic Tool Registry ]                         │
│                 - get_vehicle_profile()                                 │
│                 - query_telemetry()                                     │
│                 - query_events()                                        │
│                 - query_diagnostics()                                   │
│                 - compare_sessions()                                    │
└─────────────────────────────────────────────────────────────────────────┘
```

### Non-Negotiable Invariants
1. **Zero Actuation / Zero Transmission:** The AI layer possesses no code pathways, network endpoints, or privileges to transmit CAN frames, toggle ECU outputs, or flash calibrations.
2. **Zero Direct Memory Access:** The AI cannot inspect or alter internal process memory of the CAN listener or storage threads.
3. **Deterministic Tool Gating:** All factual data presented to the user (e.g. "RPM reached 6,240") must originate from deterministic tool query outputs. If the model makes a numerical claim without tool backing, it is considered a safety defect.

---

## 2. Structured Findings Input Contract

The AI does not receive thousands of raw CAN frames. It receives curated, structured analysis packages:

```json
{
  "vehicle": {
    "vehicle_id": "veh_foxbody_ls3",
    "name": "1989 Mustang LX (LS3 Swap)",
    "engine": "GM 6.2L LS3 V8",
    "ecu_type": "Holley Terminator X MAX",
    "fuel_type": "93 Octane Pump Gas",
    "modifications": [
      {"date": "2026-08-15", "mod": "BTR Stage 2 Camshaft installed"},
      {"date": "2026-08-20", "mod": "1-7/8 Long Tube Headers installed"}
    ]
  },
  "session": {
    "session_id": "sess_20260905_wot01",
    "type": "Street Drive with WOT Pulls",
    "duration_s": 1240.5,
    "valid_telemetry_pct": 99.8
  },
  "baseline": {
    "idle_rpm_median": 850,
    "idle_map_kpa_median": 48.2,
    "cruise_fuel_learn_iqr": [-1.5, 2.1],
    "coolant_normal_range": [182.0, 198.0]
  },
  "detected_events": [
    {
      "event_type": "WOT_PULL",
      "timestamp": 1725578410.0,
      "duration_s": 4.6,
      "peak_rpm": 5850,
      "peak_map_kpa": 98.4
    }
  ],
  "diagnostics": [
    {
      "diagnostic_id": "DIAG_FUEL_HIGH_LOAD_DEV",
      "severity": "warning",
      "observation": "Closed-loop fuel learn averaged +8.2% across 4 high-load events.",
      "evidence": [
        {"metric": "rpm_band", "value": "4800-5600 rpm"},
        {"metric": "mean_correction", "value": "+8.2%"}
      ],
      "possible_causes": [
        "VE table values low in high-load region",
        "Fuel pressure drop under high demand",
        "Exhaust leak upstream of wideband"
      ],
      "recommended_tests": [
        "Verify mechanical fuel rail pressure holds 58 PSI during WOT",
        "Perform smoke test on header collector joints"
      ],
      "confidence": 0.94
    }
  ]
}
```

---

## 3. "Ask Your Engine" Deterministic Tool Registry

In conversational mode, the LLM utilizes function calling against a deterministic API:

```python
class EngineCopilotTools(Protocol):
    def get_vehicle_profile(self) -> dict: ...
    def get_recent_sessions(self, limit: int = 5) -> list[dict]: ...
    def get_session_summary(self, session_id: str) -> dict: ...
    def query_telemetry(
        self, session_id: str, channels: list[str], start_time: float, end_time: float
    ) -> dict: ...
    def query_events(
        self, session_id: str, event_type: Optional[str] = None
    ) -> list[dict]: ...
    def query_diagnostics(
        self, session_id: str, min_severity: str = "info"
    ) -> list[dict]: ...
    def compare_sessions(
        self, session_a: str, session_b: str, channel: str
    ) -> dict: ...
    def get_modification_history(self) -> list[dict]: ...
```

---

## 4. Provider-Agnostic LLM Interface

To prevent vendor lock-in, the AI gateway exposes a unified interface:

```python
class LLMProvider(Protocol):
    async def generate_response(
        self,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
        temperature: float = 0.2
    ) -> LLMResponse: ...
```

Implementations:
1. `GoogleGeminiProvider` (Gemini 2.5/3.8 Flash & Pro)
2. `AnthropicClaudeProvider` (Claude 3.5 Sonnet)
3. `OpenAIProvider` (GPT-4o)
4. `LocalOllamaProvider` (Llama 3 / Mistral via local HTTP API)
