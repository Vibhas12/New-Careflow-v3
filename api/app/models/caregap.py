"""Stored care-gap alerts. Detection is rule-based (services/care_gaps.py); people approve or dismiss."""
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CareGapAlert(Base):
    __tablename__ = 'care_gap_alerts'
    __table_args__ = (CheckConstraint("status IN ('Open','Actioned','Dismissed','Resolved')", name='status'),
                      CheckConstraint("priority IN ('high','med','low')", name='priority'),
                      Index('ix_care_gap_alerts_patient_status', 'patient_id', 'status'))
    id: Mapped[str] = mapped_column(String(120), primary_key=True)          # ALR-<rule>-<entity>: stable across scans
    rule: Mapped[str] = mapped_column(String(32), index=True)
    category: Mapped[str] = mapped_column(String(80))
    rule_name: Mapped[str] = mapped_column(String(160))
    patient_id: Mapped[str] = mapped_column(ForeignKey('patients.id', ondelete='CASCADE'))
    entity: Mapped[str] = mapped_column(String(64))                          # the record that triggered it
    priority: Mapped[str] = mapped_column(String(4))
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSON)
    action: Mapped[dict] = mapped_column(JSON)                               # suggested next action (requires approval)
    assignee: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    status: Mapped[str] = mapped_column(String(10), default='Open')
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actioned_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    actioned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    task_id: Mapped[str | None] = mapped_column(ForeignKey('tasks.id', ondelete='SET NULL'))
    dismissed_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    dismiss_reason: Mapped[str | None] = mapped_column(Text)
    # LLM wording of the recommended action (services/recommendation_agent.py). Detection stays rule-based.
    ai_text: Mapped[str | None] = mapped_column(Text)
    ai_rationale: Mapped[str | None] = mapped_column(Text)
    ai_task_title: Mapped[str | None] = mapped_column(String(160))
    ai_model: Mapped[str | None] = mapped_column(String(80))
    ai_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ai_source_hash: Mapped[str | None] = mapped_column(String(64))   # facts the wording was based on – re-worded when they change
    ai_error: Mapped[str | None] = mapped_column(Text)
