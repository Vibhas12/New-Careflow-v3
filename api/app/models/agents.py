"""One row per requested AI agent run – who asked, which agent, outcome, model, time taken.
Never stores prompts or model output (those stay on the record they belong to, e.g. care_gap_alerts.ai_text);
only a hash of the de-identified input, so repeated runs on the same facts can be recognised."""
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

RUN_STATUSES = ('ok', 'failed', 'withheld', 'blocked', 'limited', 'disabled')
CALLED_LLM = ('ok', 'failed', 'withheld')      # statuses where the provider was actually called – these count towards limits


class AgentRun(Base):
    __tablename__ = 'agent_runs'
    __table_args__ = (CheckConstraint("status IN ('ok','failed','withheld','blocked','limited','disabled')", name='status'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    agent: Mapped[str] = mapped_column(String(40), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), index=True)
    patient_id: Mapped[str | None] = mapped_column(String(16), index=True)   # no FK: the run log outlives record edits
    entity: Mapped[str | None] = mapped_column(String(120))                   # e.g. the alert id
    status: Mapped[str] = mapped_column(String(10))
    model: Mapped[str | None] = mapped_column(String(80))
    attempts: Mapped[list | None] = mapped_column(JSON)                       # [{model, outcome}] – provider fallback chain
    error: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[int | None] = mapped_column(Integer)
    issues: Mapped[list | None] = mapped_column(JSON)                         # verifier / privacy findings
    input_hash: Mapped[str | None] = mapped_column(String(64))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
