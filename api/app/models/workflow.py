"""Tasks, reminders and in-app notifications."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Task(Base):
    __tablename__ = 'tasks'
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    patient_id: Mapped[str | None] = mapped_column(ForeignKey('patients.id', ondelete='CASCADE'), index=True)
    priority: Mapped[str | None] = mapped_column(String(4))
    assignee: Mapped[str | None] = mapped_column(ForeignKey('users.id'), index=True)
    created: Mapped[date | None] = mapped_column(Date)
    due: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str | None] = mapped_column(String(20))
    source: Mapped[str | None] = mapped_column(String(60))
    description: Mapped[str | None] = mapped_column(Text)
    completed_on: Mapped[date | None] = mapped_column(Date)
    alert_id: Mapped[str | None] = mapped_column(String(80))
    test_id: Mapped[str | None] = mapped_column(ForeignKey('diagnostic_tests.id', ondelete='SET NULL'))   # "schedule this test" tasks
    source_batch_id: Mapped[str | None] = mapped_column(ForeignKey('ingestion_batches.id'))
    extra: Mapped[dict | None] = mapped_column(JSON)
    events: Mapped[list['TaskEvent']] = relationship(cascade='all, delete-orphan', order_by='TaskEvent.seq')


class TaskEvent(Base):
    __tablename__ = 'task_events'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey('tasks.id', ondelete='CASCADE'), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    by_name: Mapped[str | None] = mapped_column(String(120))
    text: Mapped[str | None] = mapped_column(Text)


class Reminder(Base):
    __tablename__ = 'reminders'
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    kind: Mapped[str | None] = mapped_column(String(20))
    ref_id: Mapped[str | None] = mapped_column(String(16))
    patient_id: Mapped[str | None] = mapped_column(ForeignKey('patients.id', ondelete='CASCADE'), index=True)
    offset_label: Mapped[str | None] = mapped_column(String(10))
    channel: Mapped[str | None] = mapped_column(String(10))
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str | None] = mapped_column(String(20))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    label: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str | None] = mapped_column(Text)
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    extra: Mapped[dict | None] = mapped_column(JSON)


class Notification(Base):
    __tablename__ = 'notifications'
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    to_user: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    to_role: Mapped[str | None] = mapped_column(String(16))
    title: Mapped[str | None] = mapped_column(String(200))
    text: Mapped[str | None] = mapped_column(Text)
    route: Mapped[str | None] = mapped_column(String(40))
    patient_id: Mapped[str | None] = mapped_column(ForeignKey('patients.id', ondelete='CASCADE'))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    level: Mapped[str | None] = mapped_column(String(10))
    extra: Mapped[dict | None] = mapped_column(JSON)
