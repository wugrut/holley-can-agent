# AI Architecture & Calibration Reasoning Specification
### Google Gemini 2.5 Agentic Calibration Co-Driver for Holley EFI

**System:** Holley EFI Intelligence Copilot  
**Tier:** Agentic AI Reasoning & Calibration Decision-Support  
**Backend:** Official `google-genai` SDK (`gemini-2.5-flash` / `gemini-2.5-pro`) + Deterministic Fallback  
**Vehicle:** 1980 Ford Fairmont 4.8L Turbo LS + GM 4L80E  

---

## 1. Safety Firewall & Architectural Boundary

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        PHYSICAL CONTROL BOUNDARY                        │
│                                                                         │
│   HOLLEY ECU ◄───► [ Metri-Pack CAN 1 ] ◄───► [ Datalog .dl / .dlz ]    │
│                               ▲                                         │
│                               │ HARDWARE FIREWALL: ZERO WRITE ACCESS    │
│                               ▼                                         │
│                 [ Deterministic Calibration Core ]                      │
│                  - 16×16 VE Matrix Optimizer (NumPy)                    │
│                  - Post-Pull WOT Slicer & Detector                      │
│                  - 1:1 Boost-Referenced Rail Differential Auditor       │
│                  - 4L80E Converter Slip & Staging Analyzer              │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ Typed Python Tool Execution
                                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│               GEMINI 2.5 AGENTIC REASONING ENGINE                       │
│                                                                         │
│   [ Google GenAI SDK (Client) ] ── Gemini 2.5 Flash / Pro               │
│                               ▲                                         │
│                               ▼                                         │
│                 [ Grounded Domain Tools ]                               │
│                 - get_vehicle_specs()                                   │
│                 - analyze_datalog(path)                                 │
│                 - audit_fuel_system(path)                               │
│                 - get_ve_recommendations(include_learn)                 │
│                 - list_available_datalogs()                             │
└─────────────────────────────────────────────────────────────────────────┘
```

### Non-Negotiable Invariants
1. **Zero Actuation / Zero Calibration Flashing:** The AI layer possesses no code pathways, network endpoints, or privileges to transmit flash commands or modify ECU EEPROM memory. All tuning suggestions are presented as formatted decision support for the tuner.
2. **Deterministic Tool Gating (Zero Hallucination):** Every numerical metric (RPM, AFR, boost PSI, rail differential, VE corrections) must originate from executed tool calls. The model is forbidden from inventing telemetry values.
3. **Offline Reliability:** If an API key is not supplied or the tuner is at a remote track without internet, the system automatically falls back to the local deterministic rule engine (`CopilotService`).

---

## 2. Target Platform Grounding Parameters

The Gemini system instruction seeds the agent with the verified specifications of the 1980 Ford Fairmont:

```json
{
  "vehicle": "1980 Ford Fairmont 4-Door 'Boxtop' (Fox Platform, ~3300 lbs)",
  "engine": "GM 4.8L Gen III Iron Block LS (LM7/LR4)",
  "camshaft": "Elgin E-1840-P Sloppy Stage 2 (228/230 @ .050, .585/.585 lift, 112 LSA)",
  "turbocharger": "VS Racing 78/75 on Hooker BlackHeart manifold, 3-inch FMIC, 50mm BOV",
  "fuel_system": "Racetronix 420 LPH pump, 58 PSI base mechanical rail pressure (1:1 boost-ref)",
  "injectors": "Siemens Deka 80 lb/hr High-Z + Continental Flex Fuel (E85 / 93 Octane)",
  "transmission": "GM 4L80E (Alto Red Eagle clutches, TransGo HD2) + Yank 3600 RPM stall converter",
  "staging": "3rd-Gear Mechanical Bind-Up Sloppy Transbrake (3000-3200 RPM @ 0-5 deg BTDC)",
  "rear_axle": "Ford 8.8-inch SN95 (3.73:1 gears, 245/45R17 drag radials)",
  "limits": {
    "base_fuel_psi": 58.0,
    "standard_boost_range_psi": [12.0, 15.0],
    "pump_blend_boost_cut_psi": 17.0,
    "max_e85_boost_psi": 20.0,
    "redline_rpm": 6800.0
  }
}
```

---

## 3. Grounded Agentic Tools

The `GeminiAgent` registers Python callable tools directly with `google.genai.types.GenerateContentConfig(tools=[...])`:

### `audit_fuel_system(file_path: Optional[str] = None)`
Audits whether mechanical fuel pressure properly tracked boost 1:1:
$$\Delta P = P_{\text{fuel}} - P_{\text{boost}} \approx 58.0\text{ PSI}$$
- Evaluates every sample where $P_{\text{boost}} \ge 2.0\text{ PSI}$.
- Identifies critical drops where effective differential falls below $53.0\text{ PSI}$.
- Flags pump flow starvation, voltage sags, or regulator vacuum reference failures.

### `get_ve_recommendations(include_learn: bool = True)`
Returns the 16×16 VE cell hit matrix, transient exclusions, top rich/lean trim cells, and the formatted TSV string for Holley software clipboard pasting.
- Filters out $|d\text{TPS}/dt| > 25\%/\text{s}$ and $|d\text{MAP}/dt| > 65\text{ kPa/s}$.
- Filters out $\text{ECT} < 160^\circ\text{F}$ and DFCO events.
- Folds both Closed-Loop Compensation % and Fuel Learn % into base VE cells:
  $$\text{Target\_VE} = \text{Base\_VE} \times \left(1 + \frac{\text{CL\_Comp} + \text{Fuel\_Learn}}{100}\right)$$

### `analyze_datalog(file_path: Optional[str] = None)`
Parses Terminator X V3 (`0x0095365F`, 2512 bytes/row) and Holley V6 (`0x0085F41F`, 4120 bytes/row) binary datalogs.
- Automatically handles RLE decompressor and 4-byte endian swaps for `.dlz` files.
- Extracts WOT intervals, peak boost, wideband AFR error against target AFR, minimum rail pressure, max injector duty cycle, and knock retard.

---

## 4. Zero-Touch Auto-Pilot Integration

When the background file watcher (`AutoHandoffWatcher`) detects a new datalog save in `Documents\Holley\Terminator X V3\Data Logs\`:
1. Slices out WOT intervals and runs the post-pull detector.
2. Ingests steady-state points into `VETableOptimizer`.
3. Dispatches an automated background prompt to Gemini:
   ```text
   AUTOMATED POST-PULL AUDIT: A new Holley datalog 'run_04.dl' was just saved.
   • Peak Boost: 14.2 PSI @ 6,100 RPM
   • Average AFR: 11.4 vs Target 11.5 (Error: -0.10)
   • Minimum Fuel Pressure: 72.2 PSI (effective delta: 58.0 PSI vs 58.0 PSI target)
   • Max Injector Duty Cycle: 68.4%
   Audit this run: confirm if 1:1 boost-referenced fuel pressure held safe,
   summarize wideband tracking, and give 2-3 specific tuning takeaways.
   ```
4. Gemini's response is pushed in real time over WebSocket to the web studio chat, with audible announcement via browser speech synthesis.
5. The updated 16×16 VE table is automatically written to `COPY 16x16 VE TABLE (CTRL+V).txt` on disk.
