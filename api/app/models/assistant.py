"""AI Care Assistant: per-user conversation and the actions it proposes (nothing is executed without approval)."""
from datetime import date, datetime

from sqlalchemy import JSON, CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AssistantMessage(Base):
    __tablename__ = 'assistant_messages'
    __table_args__ = (CheckConstraint("role IN ('user','ai')", name='role'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    role: Mapped[str] = mapped_column(String(4))
    text: Mapped[str] = mapped_column(Text)                         # user question, or the answer's introduction
    patient_id: Mapped[str | None] = mapped_column(ForeignKey('patients.id', ondelete='SET NULL'))
    payload: Mapped[dict | None] = mapped_column(JSON)              # answer blocks + agent trace


class AssistantProposal(Base):
    __tablename__ = 'assistant_proposals'
    __table_args__ = (CheckConstraint("type IN ('task','reminder')", name='type'),
                      CheckConstraint("status IN ('Proposed','Approved','Rejected')", name='status'))
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    patient_id: Mapped[str] = mapped_column(ForeignKey('patients.id', ondelete='CASCADE'), index=True)
    type: Mapped[str] = mapped_column(String(8))
    title: Mapped[str] = mapped_column(Text)
    assignee: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    due: Mapped[date | None] = mapped_column(Date)
    priority: Mapped[str] = mapped_column(String(4), default='med')
    channel: Mapped[str | None] = mapped_column(String(10))
    message: Mapped[str | None] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default='Proposed')
    decided_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_ref: Mapped[str | None] = mapped_column(String(16))      # created task / reminder id
