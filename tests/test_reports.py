"""
Unit tests for ReportGenerator and HealthScores.
"""

import time
import pytest

from app.diagnostics.finding import DiagnosticEvidenceItem, StructuredDiagnostic
from app.reports.generator import HealthScores, ReportGenerator
from app.sessions.metadata import SessionMetadata, SessionType
from app.vehicle.profile import VehicleProfile


class TestReports:
    def test_health_score_calculation(self):
        # Clean run
        scores_clean = HealthScores.calculate([], valid_sample_pct=100.0)
        assert scores_clean.overall == 100
        assert scores_clean.fueling == 100

        # Run with fueling warning
        diag_fuel = StructuredDiagnostic(
            diagnostic_id="DIAG_FUEL_HIGH_LOAD_DEV",
            title="High-Load Fueling Deviation",
            severity="warning",
            category="fueling",
            observation="Fuel learn +8.2%",
        )
        scores_warning = HealthScores.calculate([diag_fuel], valid_sample_pct=100.0)
        assert scores_warning.fueling == 92
        assert scores_warning.overall < 100

    def test_report_generator_markdown_output(self):
        profile = VehicleProfile(name="Foxbody LS3", engine_name="6.2L LS3")
        gen = ReportGenerator(profile)

        session = SessionMetadata(
            session_id="sess_wot_001",
            session_type=SessionType.WOT_PULL,
            start_time=time.time(),
            sample_count=200,
            valid_sample_pct=99.5,
        )

        diag = StructuredDiagnostic(
            diagnostic_id="DIAG_FUEL_HIGH_LOAD_DEV",
            title="High-Load Fueling Deviation",
            severity="warning",
            category="fueling",
            observation="Fuel learn +8.2%",
            inferred_condition="High-load airflow exceeds base VE table.",
            evidence=[DiagnosticEvidenceItem("mean_fuel_learn", "+8.2%", "%")],
            possible_causes=["VE table values low", "Fuel pressure drop"],
            recommended_tests=["Verify mechanical fuel rail pressure holds 58 PSI during WOT"],
        )

        report_md = gen.generate_markdown(session, [diag])
        assert "# EFI INTELLIGENCE REPORT" in report_md
        assert "Foxbody LS3" in report_md
        assert "High-Load Fueling Deviation" in report_md
        assert "58 PSI" in report_md
        assert "Overall Health" in report_md

        report_html = gen.generate_html(session, [diag])
        assert "<!DOCTYPE html>" in report_html
        assert "EFI Intelligence Report" in report_html
