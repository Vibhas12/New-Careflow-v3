"""Audit log, append-only priority history, and data-import (ingestion) tables."""
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AuditLog(Base):
    __tablename__ = 'audit_log'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    user_id: Mapped[str | None] = mapped_column(String(32))
    user_name: Mapped[str | None] = mapped_column(String(120))
    role: Mapped[str | None] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(120))
    patient_id: Mapped[str | None] = mapped_column(ForeignKey('patients.id', ondelete='SET NULL'), index=True)
    entity: Mapped[str | None] = mapped_column(String(80))
    detail: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(String(64))


class PriorityHistory(Base):
    """Append-only. Database triggers (see the initial migration) reject UPDATE and DELETE."""
    __tablename__ = 'priority_history'
    __table_args__ = (CheckConstraint("previous_priority IS NULL OR previous_priority IN ('high','med','low')", name='previous'),
                      CheckConstraint("new_priority IN ('high','med','low')", name='new'),
                      CheckConstraint('length(trim(comment)) >= 5', name='comment'),
                      Index('ix_priority_history_patient', 'patient_id', 'id'))
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey('patients.id'))
    previous_priority: Mapped[str | None] = mapped_column(String(4))
    new_priority: Mapped[str] = mapped_column(String(4))
    comment: Mapped[str] = mapped_column(Text)
    user_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    user_name: Mapped[str] = mapped_column(String(120))
    user_role: Mapped[str] = mapped_column(String(16))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IngestionBatch(Base):
    __tablename__ = 'ingestion_batches'
    __table_args__ = (CheckConstraint("status IN ('Rejected','Failed','Needs Review','Imported','Partially Imported','Cancelled')", name='status'),)
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str | None] = mapped_column(String(8))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    stored_path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    message: Mapped[str | None] = mapped_column(Text)
    uploaded_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extraction_method: Mapped[str | None] = mapped_column(String(40))
    n_records: Mapped[int] = mapped_column(Integer, default=0)
    n_imported: Mapped[int] = mapped_column(Integer, default=0)
    n_skipped: Mapped[int] = mapped_column(Integer, default=0)
    n_failed: Mapped[int] = mapped_column(Integer, default=0)


class IngestionRecord(Base):
    __tablename__ = 'ingestion_records'
    __table_args__ = (CheckConstraint("match_status IN ('matched','new','uncertain','duplicate','invalid')", name='match_status'),
                      CheckConstraint("decision IN ('pending','import','skip')", name='decision'),
                      CheckConstraint("result IS NULL OR result IN ('saved','skipped','failed')", name='result'))
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey('ingestion_batches.id', ondelete='CASCADE'), index=True)
    row_no: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))
    raw: Mapped[dict | None] = mapped_column(JSON)
    mapped: Mapped[dict | None] = mapped_column(JSON)
    match_status: Mapped[str] = mapped_column(String(10))
    matched_patient_id: Mapped[str | None] = mapped_column(ForeignKey('patients.id'))
    candidates: Mapped[list | None] = mapped_column(JSON)
    issues: Mapped[list | None] = mapped_column(JSON)
    decision: Mapped[str] = mapped_column(String(8), default='pending')
    result: Mapped[str | None] = mapped_column(String(8))
    result_message: Mapped[str | None] = mapped_column(Text)
    saved_entity: Mapped[str | None] = mapped_column(String(40))


class Document(Base):
    __tablename__ = 'documents'
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    batch_id: Mapped[str | None] = mapped_column(ForeignKey('ingestion_batches.id'))
    patient_id: Mapped[str | None] = mapped_column(ForeignKey('patients.id', ondelete='SET NULL'), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str | None] = mapped_column(String(8))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    stored_path: Mapped[str] = mapped_column(Text)
    doc_type: Mapped[str | None] = mapped_column(String(60))
    extracted_text: Mapped[str | None] = mapped_column(Text)
    extraction_method: Mapped[str | None] = mapped_column(String(40))
    uploaded_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
