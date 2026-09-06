"""
Automotive health report generator supporting Markdown, HTML, and text formats.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.diagnostics.finding import StructuredDiagnostic
from app.sessions.metadata import SessionMetadata
from app.vehicle.profile import VehicleProfile


@dataclass
class HealthScores:
    """Calculated automotive domain health scores (0 - 100)."""
    overall: int = 100
    fueling: int = 100
    idle: int = 100
    sensors: int = 100
    thermal: int = 100
    electrical: int = 100

    @classmethod
    def calculate(
        cls,
        diagnostics: List[StructuredDiagnostic],
        valid_sample_pct: float = 100.0,
    ) -> HealthScores:
        """Calculates health scores penalized by diagnostic findings and data validity."""
        scores = {
            "fueling": 100,
            "idle": 100,
            "sensors": 100,
            "thermal": 100,
            "electrical": 100,
        }

        # Apply diagnostic penalties
        for d in diagnostics:
            penalty = 20 if d.severity == "critical" else 8
            cat = d.category.lower()
            if cat in scores:
                scores[cat] = max(20, scores[cat] - penalty)

        # Apply data validity penalty
        if valid_sample_pct < 95.0:
            drop = int((95.0 - valid_sample_pct) * 0.8)
            scores["sensors"] = max(30, scores["sensors"] - drop)

        overall = int(sum(scores.values()) / len(scores))
        return cls(
            overall=overall,
            fueling=scores["fueling"],
            idle=scores["idle"],
            sensors=scores["sensors"],
            thermal=scores["thermal"],
            electrical=scores["electrical"],
        )


class ReportGenerator:
    """Generates structured intelligence reports from sessions and diagnostics."""

    def __init__(self, vehicle_profile: VehicleProfile) -> None:
        self.profile = vehicle_profile

    def generate_markdown(
        self,
        session: SessionMetadata,
        diagnostics: List[StructuredDiagnostic],
    ) -> str:
        """Renders GitHub-flavored markdown report."""
        scores = HealthScores.calculate(diagnostics, session.valid_sample_pct)
        date_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(session.start_time))

        lines = [
            "# EFI INTELLIGENCE REPORT",
            "",
            f"**Vehicle:** {self.profile.name} ({self.profile.engine_name})  ",
            f"**ECU:** {self.profile.ecu_type}  ",
            f"**Session ID:** `{session.session_id}`  ",
            f"**Date:** {date_str}  ",
            f"**Duration:** {session.sample_count / 20.0:.1f}s (estimated) | **Data Validity:** {session.valid_sample_pct:.1f}%",
            "",
            "---",
            "",
            f"## Overall Health: {scores.overall} / 100",
            "",
            "| System Domain | Score | Status |",
            "|---------------|-------|--------|",
            f"| **Fueling** | {scores.fueling}/100 | {'Optimal' if scores.fueling > 85 else 'Needs Review'} |",
            f"| **Idle Stability** | {scores.idle}/100 | {'Optimal' if scores.idle > 85 else 'Needs Review'} |",
            f"| **Sensors** | {scores.sensors}/100 | {'Optimal' if scores.sensors > 85 else 'Needs Review'} |",
            f"| **Thermal** | {scores.thermal}/100 | {'Optimal' if scores.thermal > 85 else 'Needs Review'} |",
            f"| **Electrical** | {scores.electrical}/100 | {'Optimal' if scores.electrical > 85 else 'Needs Review'} |",
            "",
            "---",
            "",
            "## KEY FINDINGS",
            "",
        ]

        if not diagnostics:
            lines.append("✓ **No abnormal events or active diagnostics detected.** Engine telemetry adhered to normal operating parameters.")
        else:
            for i, d in enumerate(diagnostics, 1):
                icon = "⚠️" if d.severity == "warning" else "🚨"
                lines.append(f"### {i}. {icon} {d.title} ({d.severity.upper()})")
                lines.append(f"**Observation:** {d.observation}")
                lines.append(f"**Inferred Condition:** {d.inferred_condition}")
                if d.evidence:
                    lines.append("**Evidence:**")
                    for ev in d.evidence:
                        lines.append(f"- {ev.name}: `{ev.value}` {ev.unit}")
                if d.possible_causes:
                    lines.append("**Possible Causes:**")
                    for c in d.possible_causes:
                        lines.append(f"1. {c}")
                if d.recommended_tests:
                    lines.append("**Recommended Next Tests:**")
                    for t in d.recommended_tests:
                        lines.append(f"- [ ] {t}")
                lines.append("")

        lines.extend([
            "---",
            "",
            "## RECOMMENDED NEXT ACTION",
            "",
        ])

        if diagnostics:
            # First action item from top diagnostic
            top_test = diagnostics[0].recommended_tests[0] if diagnostics[0].recommended_tests else "Review detailed session log."
            lines.append(f"> **Priority Action:** {top_test}")
        else:
            lines.append("> **Priority Action:** Continue regular vehicle operation; baseline established successfully.")

        lines.append("\n*Report generated by EFI Intelligence Copilot.*")
        return "\n".join(lines)

    def generate_html(
        self,
        session: SessionMetadata,
        diagnostics: List[StructuredDiagnostic],
    ) -> str:
        """Renders standalone HTML report with embedded responsive styling."""
        md = self.generate_markdown(session, diagnostics)
        # Wrap simple styled template
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>EFI Intelligence Report - {session.session_id}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; padding: 2rem; max-width: 900px; margin: 0 auto; }}
        h1 {{ color: #38bdf8; border-bottom: 2px solid #1e293b; padding-bottom: 0.5rem; }}
        h2 {{ color: #e2e8f0; margin-top: 2rem; }}
        h3 {{ color: #f59e0b; }}
        table {{ width: 100%; border-collapse: collapse; margin: 1.5rem 0; background: #1e293b; border-radius: 8px; overflow: hidden; }}
        th, td {{ padding: 0.75rem 1rem; text-align: left; border-bottom: 1px solid #334155; }}
        th {{ background: #0f172a; color: #94a3b8; }}
        blockquote {{ background: #1e293b; border-left: 4px solid #38bdf8; padding: 1rem; margin: 1.5rem 0; border-radius: 4px; }}
        code {{ background: #1e293b; padding: 0.2rem 0.4rem; border-radius: 4px; color: #38bdf8; }}
    </style>
</head>
<body>
    <pre style="white-space: pre-wrap; font-family: inherit;">{md}</pre>
</body>
</html>"""
        return html
