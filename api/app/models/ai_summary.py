"""Stored AI patient summary (one per patient, multi-agent phase 3). Written only when a person clicks "Generate AI summary".
Hidden as soon as the patient's records change (source_hash no longer matches the Context agent's fingerprint)."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AiSummary(Base):
    __tablename__ = 'ai_summaries'
    patient_id: Mapped[str] = mapped_column(ForeignKey('patients.id', ondelete='CASCADE'), primary_key=True)
    source_hash: Mapped[str | None] = mapped_column(String(64))       # Context agent fingerprint the summary was written from
    payload: Mapped[dict | None] = mapped_column(JSON)                 # {overview, sections} – statements citing source numbers
    model: Mapped[str | None] = mapped_column(String(80))
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generated_by: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'))
    error: Mapped[str | None] = mapped_column(Text)                    # last requested attempt failed / withheld
    error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
