"""
gemini_agent.py — Agentic EFI Calibration & Diagnostics Copilot powered by Google Gemini.

Integrates the official google-genai SDK (Gemini 2.5 Flash / Pro) with grounded
tools for Holley Terminator X / MAX datalogs (.dl / .dlz / .csv), 16x16 VE matrix
optimization, 1:1 boost-referenced fuel pressure auditing, and 4L80E drivetrain analysis.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

from .copilot_service import CopilotService
from .dl_parser import HolleyDatalogParser, discover_local_holley_files
from .tune_optimizer import FAIRMONT_PLATFORM_SPEC, VETableOptimizer

logger = logging.getLogger(__name__)

GEMINI_SYSTEM_INSTRUCTION = """
You are the Gemini EFI Intelligence Copilot, an expert automotive calibration engineer and diagnostics reasoning assistant.
You assist a tuner and drag racer working with a 1980 Ford Fairmont powered by a Holley Terminator X MAX ECU.

TARGET VEHICLE SPECIFICATIONS:
- Vehicle: 1980 Ford Fairmont 4-Door "Boxtop" (Fox body chassis, ~3,300 lbs curb weight)
- Engine: GM 4.8L Iron-Block Gen III LS (LM7/LR4)
- Camshaft: Elgin E-1840-P "Sloppy Stage 2" (228°/230° @ .050", .585"/.585" lift, 112° LSA) + PAC 1218 beehive springs
- Turbocharger: VS Racing 78/75 cast turbo on Hooker BlackHeart manifold, 3" cold side FMIC, Pre-TB 50mm BOV, 3" exhaust with electric cutout
- Ignition: Stock LS Coil-Near-Plug (CNP), NGK BR7EF spark plugs gapped @ 0.022"
- Fuel System: Racetronix 420 LPH in-tank pump, 58 PSI base mechanical rail pressure referenced 1:1 with boost (Aeromotive regulator), Siemens Deka 80 lb/hr High-Z injectors, Continental Flex Fuel sensor (E85 / 93 Octane blend / E40)
- Transmission: GM 4L80E 4-speed automatic (TransGo HD2 shift kit, Alto Red Eagle clutches), Yank 3600 RPM stall converter
- Staging / Launch: 3rd-gear mechanical bind-up "Sloppy Transbrake" (targets 3000–3200 RPM @ 0°–5° BTDC on 2-step)
- Drivetrain: Ford 8.8" rear axle (3.73:1 ring & pinion), 245/45R17 drag radials (~25.85" rolling diameter)
- Safety & Boost Limits:
  * Standard boost: 12.0 – 15.0 PSI
  * Pump gas blend cut: 17.0 PSI hard safety threshold
  * Max E85 boost: 20.0 PSI strictly on verified high-ethanol fuel
  * Max RPM redline: 6,800 RPM

MANDATORY CALIBRATION & REASONING RULES:
1. NEVER FABRICATE DATA: Every number, RPM, AFR, boost pressure, fuel pressure, or trim must come strictly from loaded datalogs or tool call results. If data is missing or incomplete, explicitly state what is unknown.
2. 1:1 BOOST REFERENCED FUEL PRESSURE: The fuel system uses a 1:1 boost-referenced regulator with 58 PSI base.
   Effective fuel rail delta = Fuel Pressure - MAP. At 0 PSI boost (101 kPa), rail pressure should be ~58 PSI. At 14 PSI boost, rail pressure MUST rise to ~72 PSI (72 - 14 = 58 PSI differential). If fuel pressure does not rise 1:1 with boost, warn the tuner immediately of potential lean out or fuel pump starvation.
3. VE TABLE LEARNING FILTERS: In steady-state VE table optimization, explain why transient throttle changes (|dTPS/dt| > 25%/s), cold coolant (ECT < 160°F), and deceleration fuel cutoff (DFCO) are excluded to prevent corrupted VE cells.
4. ACTIONABLE ADVICE: Group your response clearly:
   - 📊 Summary of Telemetry / Log Findings
   - ⚠️ Warnings & Anomalies (if any)
   - 💡 Specific Tuning Recommendations (VE adjustments, timing, fuel pressure, staging)
   - 📋 Next Steps for the Tuner
"""


class GeminiAgent:
    """
    Agentic companion that connects Gemini 2.5 with Holley EFI calibration tools.
    Falls back to offline deterministic rule engine if API key is not supplied.
    """

    def __init__(
        self,
        ve_optimizer: Optional[VETableOptimizer] = None,
        api_key: Optional[str] = None,
        model_name: str = "gemini-2.5-flash",
    ):
        self.ve_optimizer = ve_optimizer or VETableOptimizer(base_fuel_psi=58.0)
        self.offline_service = CopilotService(vehicle_name="1980 Ford Fairmont Turbo LS")
        self.model_name = model_name
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self._client: Optional[Any] = None

        if self._api_key and GENAI_AVAILABLE:
            try:
                self._client = genai.Client(api_key=self._api_key)
                logger.info("GeminiAgent initialized with model %s", self.model_name)
            except Exception as e:
                logger.warning("Could not initialize Gemini Client: %s", e)
                self._client = None

    def set_api_key(self, api_key: str) -> bool:
        """Dynamically update the Gemini API key from UI settings."""
        api_key = api_key.strip()
        if not api_key or not GENAI_AVAILABLE:
            self._client = None
            self._api_key = None
            return False

        try:
            self._client = genai.Client(api_key=api_key)
            self._api_key = api_key
            logger.info("Gemini Client successfully updated with new API key.")
            return True
        except Exception as e:
            logger.error("Failed to set Gemini API key: %s", e)
            return False

    @property
    def is_gemini_active(self) -> bool:
        """Returns True if live Gemini API is ready to receive prompts."""
        return self._client is not None and GENAI_AVAILABLE

    # ── Grounded Agentic Tools ──────────────────────────────────────────────

    def get_vehicle_specs(self) -> Dict[str, Any]:
        """Returns verified mechanical, engine, turbo, fuel, and transmission specifications of the Fairmont."""
        return FAIRMONT_PLATFORM_SPEC

    def list_available_datalogs(self) -> Dict[str, Any]:
        """Discovers and returns all local Holley .dl and .dlz datalogs in Documents/Holley or workspace."""
        return discover_local_holley_files()

    def analyze_datalog(self, file_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Parses a Holley .dl or .dlz binary datalog and returns comprehensive telemetry metrics:
        peak RPM, peak boost (psig), WOT AFR error, minimum fuel pressure, injector duty cycle, and knock.
        """
        if not file_path:
            discovered = discover_local_holley_files()
            if not discovered["datalogs"]:
                return {"error": "No datalog files (.dl or .dlz) found in Documents/Holley or workspace."}
            file_path = discovered["datalogs"][0]["path"]

        try:
            parser = HolleyDatalogParser(file_path)
            summary = parser.summarize()
            # Also feed into VE optimizer to accumulate steady-state cells
            self.ve_optimizer.ingest_datalog(file_path)
            return summary
        except Exception as e:
            return {"error": f"Failed to parse datalog {file_path}: {e}"}

    def audit_fuel_system(self, file_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Audits the 1:1 boost-referenced fuel system on the Fairmont (58 PSI base).
        Checks whether fuel pressure rises 1:1 with boost (Fuel Pressure - MAP = 58 PSI).
        """
        if not file_path:
            discovered = discover_local_holley_files()
            if not discovered["datalogs"]:
                return {"error": "No datalogs available to audit fuel system."}
            file_path = discovered["datalogs"][0]["path"]

        try:
            parser = HolleyDatalogParser(file_path)
            rows = parser.parse_rows()
            if not rows:
                return {"error": "Empty datalog."}

            boost_rows = [r for r in rows if r.get("boost_psig", 0.0) >= 2.0]
            if not boost_rows:
                return {
                    "verdict": "NO_BOOST_DETECTED",
                    "message": "Datalog contains no intervals with boost >= 2.0 PSI.",
                    "total_samples": len(rows),
                }

            deltas: List[float] = []
            min_delta = 999.0
            max_delta = -999.0
            critical_drops: List[Dict[str, float]] = []

            for r in boost_rows:
                fp = r.get("fuel_pressure", 0.0)
                boost = r.get("boost_psig", 0.0)
                # Effective mechanical rail pressure = fp - boost
                effective = fp - boost
                deltas.append(effective)
                if effective < min_delta:
                    min_delta = effective
                if effective > max_delta:
                    max_delta = effective

                # If effective rail pressure drops below 53 PSI (base is 58), flag drop
                if effective < 53.0:
                    critical_drops.append({
                        "rpm": r.get("rpm", 0.0),
                        "boost_psi": boost,
                        "fuel_psi": fp,
                        "effective_rail_psi": round(effective, 1),
                        "timestamp_s": r.get("timestamp_s", 0.0),
                    })

            avg_delta = sum(deltas) / len(deltas)
            passed = min_delta >= 53.0 and len(critical_drops) == 0

            return {
                "verdict": "PASS" if passed else "WARNING_FUEL_PRESSURE_DROP",
                "base_target_psi": 58.0,
                "boost_samples_checked": len(boost_rows),
                "avg_effective_rail_psi": round(avg_delta, 1),
                "min_effective_rail_psi": round(min_delta, 1),
                "max_effective_rail_psi": round(max_delta, 1),
                "critical_drop_count": len(critical_drops),
                "worst_drops": critical_drops[:5],
                "explanation": (
                    "Fuel rail pressure tracked boost 1:1 with excellent differential pressure."
                    if passed else
                    f"Fuel pressure dropped below base differential (minimum effective was {min_delta:.1f} PSI vs 58 PSI target). Check fuel pump flow, voltage, or regulator reference line."
                ),
            }
        except Exception as e:
            return {"error": f"Fuel system audit failed: {e}"}

    def get_ve_recommendations(self, include_learn: bool = True) -> Dict[str, Any]:
        """
        Returns the 16x16 VE table cell hit count, suggested corrections,
        and formatted TSV string ready for Holley software clipboard copy.
        """
        payload = self.ve_optimizer.get_matrix_payload(include_learn=include_learn)
        matrix = payload.get("matrix", [])

        # Find cells with significant adjustments
        large_lean_corrections = []  # Engine was lean, needs more VE
        large_rich_corrections = []  # Engine was rich, needs less VE

        for r_idx, row in enumerate(matrix):
            rpm = row["rpm"]
            for c_idx, cell in enumerate(row["cells"]):
                map_kpa = cell["map_kpa"]
                corr = cell["correction_pct"]
                hits = cell["hits"]
                if hits >= 3:
                    if corr > 3.0:
                        large_lean_corrections.append({
                            "rpm": rpm, "map_kpa": map_kpa, "correction_pct": round(corr, 1), "hits": hits
                        })
                    elif corr < -3.0:
                        large_rich_corrections.append({
                            "rpm": rpm, "map_kpa": map_kpa, "correction_pct": round(corr, 1), "hits": hits
                        })

        large_lean_corrections.sort(key=lambda x: x["correction_pct"], reverse=True)
        large_rich_corrections.sort(key=lambda x: x["correction_pct"])

        return {
            "total_steady_state_samples": payload.get("total_samples", 0),
            "cells_with_data": payload.get("cells_populated", 0),
            "top_lean_cells_needing_more_fuel": large_lean_corrections[:5],
            "top_rich_cells_needing_less_fuel": large_rich_corrections[:5],
            "tsv_preview": payload.get("tsv_clipboard", "")[:300] + "...",
            "last_source": payload.get("last_source", "none"),
        }

    # ── Conversational Orchestration ────────────────────────────────────────

    async def ask(
        self,
        question: str,
        live_snapshot: Optional[Dict[str, Any]] = None,
        active_alerts: Optional[List[Any]] = None,
        datalog_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Processes a tuner query. Uses Gemini 2.5 with tool calling if API key is active;
        otherwise delegates to the offline deterministic rule engine.
        """
        q_clean = question.strip()
        if not q_clean:
            return {"error": "Question cannot be empty."}

        # Route to live Gemini if client is ready
        if self.is_gemini_active:
            try:
                return await self._ask_gemini(q_clean, live_snapshot, datalog_path)
            except Exception as e:
                logger.error("Gemini API call failed, falling back to offline engine: %s", e)
                # Fall through to offline engine with error notice

        # Fallback to offline rule engine
        offline_res = self.offline_service.ask(
            question=q_clean,
            snapshot=live_snapshot or {},
            active_alerts=active_alerts or [],
        )
        offline_res["engine"] = "offline_rule_synthesizer"
        offline_res["gemini_available"] = GENAI_AVAILABLE
        offline_res["has_api_key"] = bool(self._api_key)
        return offline_res

    async def _ask_gemini(
        self,
        question: str,
        live_snapshot: Optional[Dict[str, Any]] = None,
        datalog_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Executes query through Gemini 2.5 with tools enabled."""
        import asyncio

        # Tools list for Gemini
        tools = [
            self.get_vehicle_specs,
            self.list_available_datalogs,
            self.analyze_datalog,
            self.audit_fuel_system,
            self.get_ve_recommendations,
        ]

        config = types.GenerateContentConfig(
            system_instruction=GEMINI_SYSTEM_INSTRUCTION,
            temperature=0.2,
            tools=tools,
        )

        user_content = f"Tuner Question: {question}"
        if datalog_path:
            user_content += f"\nActive Datalog File: {datalog_path}"
        if live_snapshot:
            # Provide high-level live telemetry context
            rpm = live_snapshot.get("rpm", {}).get("value", 0.0)
            map_kpa = live_snapshot.get("map_kpa", {}).get("value", 101.3)
            afr = live_snapshot.get("afr_avg", {}).get("value", 14.7)
            fp = live_snapshot.get("fuel_pressure", {}).get("value", 58.0)
            user_content += f"\nLive Snapshot: RPM={rpm:.0f}, MAP={map_kpa:.1f} kPa, AFR={afr:.2f}, FuelPressure={fp:.1f} PSI"

        # Run generate_content in thread pool to avoid blocking async event loop
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._client.models.generate_content(
                model=self.model_name,
                contents=user_content,
                config=config,
            ),
        )

        answer_text = response.text or "Analysis completed."

        return {
            "question": question,
            "answer": answer_text,
            "severity": "info",
            "engine": f"gemini ({self.model_name})",
            "model": self.model_name,
            "gemini_available": True,
            "has_api_key": True,
        }

