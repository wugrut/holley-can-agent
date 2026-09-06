"""
Session manager orchestrating lifecycle, batch recording, and data integrity.
"""

from __future__ import annotations

import time
from typing import List, Optional

from app.sessions.metadata import SessionMetadata, SessionType
from app.storage.repository import TelemetryRepository
from app.telemetry.sample import NormalizedTelemetrySample


class SessionManager:
    """Controls session start, recording buffering, and finalization."""

    def __init__(self, repository: TelemetryRepository, buffer_size: int = 50) -> None:
        self.repo = repository
        self.buffer_size = buffer_size

        self.current_session: Optional[SessionMetadata] = None
        self._sample_buffer: List[NormalizedTelemetrySample] = []
        self._total_samples = 0
        self._valid_samples = 0

    @property
    def is_recording(self) -> bool:
        return self.current_session is not None

    def start_session(
        self,
        vehicle_id: str,
        session_type: SessionType = SessionType.STREET_DRIVE,
        tune_revision: Optional[str] = None,
        driver_notes: Optional[str] = None,
        ambient_temp_f: Optional[float] = None,
        ambient_pressure_kpa: Optional[float] = 101.3,
    ) -> SessionMetadata:
        """Starts a new recording session."""
        if self.is_recording:
            self.end_session()

        meta = SessionMetadata(
            vehicle_id=vehicle_id,
            session_type=session_type,
            start_time=time.time(),
            tune_revision=tune_revision,
            driver_notes=driver_notes,
            ambient_temp_f=ambient_temp_f,
            ambient_pressure_kpa=ambient_pressure_kpa,
        )

        self.repo.insert_session(
            session_id=meta.session_id,
            vehicle_id=meta.vehicle_id,
            session_type=meta.session_type.value,
            start_time=meta.start_time,
            tune_revision=meta.tune_revision,
            driver_notes=meta.driver_notes,
            ambient_temp_f=meta.ambient_temp_f,
            ambient_pressure_kpa=meta.ambient_pressure_kpa,
        )

        self.current_session = meta
        self._sample_buffer = []
        self._total_samples = 0
        self._valid_samples = 0
        return meta

    def record_sample(self, sample: NormalizedTelemetrySample) -> None:
        """Appends sample to write buffer and flushes when buffer threshold is met."""
        if not self.is_recording or self.current_session is None:
            return

        self._sample_buffer.append(sample)
        self._total_samples += 1
        if sample.overall_quality_score >= 0.8:
            self._valid_samples += 1

        if len(self._sample_buffer) >= self.buffer_size:
            self.flush()

    def flush(self) -> None:
        """Flushes buffered samples to persistent storage."""
        if not self._sample_buffer or self.current_session is None:
            return

        self.repo.insert_telemetry_batch(
            session_id=self.current_session.session_id,
            samples=self._sample_buffer,
        )
        self._sample_buffer = []

    def end_session(self) -> Optional[SessionMetadata]:
        """Finalizes and closes current session."""
        if not self.is_recording or self.current_session is None:
            return None

        self.flush()
        now = time.time()
        self.current_session.end_time = now
        self.current_session.sample_count = self._total_samples

        valid_pct = (self._valid_samples / self._total_samples * 100.0) if self._total_samples > 0 else 100.0
        self.current_session.valid_sample_pct = round(valid_pct, 2)

        self.repo.update_session_summary(
            session_id=self.current_session.session_id,
            end_time=now,
            sample_count=self._total_samples,
            valid_sample_pct=self.current_session.valid_sample_pct,
        )

        closed = self.current_session
        self.current_session = None
        return closed
