"""Appointments, diagnostic tests, referrals, prescriptions and consultations."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Appointment(Base):
    __tablename__ = 'appointments'
    # A doctor can hold only one ACTIVE appointment per slot – enforced by the database, not only by the API check.
    __table_args__ = (Index('ux_appointments_doctor_slot', 'doctor_id', 'appt_date', 'appt_time', unique=True,
                            sqlite_where=text("status IN ('Scheduled','Confirmed')"), postgresql_where=text("status IN ('Scheduled','Confirmed')")),)
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey('patients.id', ondelete='CASCADE'), index=True)
    doctor_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'), index=True)
    dept: Mapped[str | None] = mapped_column(String(64))
    appt_date: Mapped[date] = mapped_column(Date, index=True)
    appt_time: Mapped[str | None] = mapped_column(String(5))          # HH:MM
    type: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20))
    created_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    booked_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    notes: Mapped[str | None] = mapped_column(Text)
    source_batch_id: Mapped[str | None] = mapped_column(ForeignKey('ingestion_batches.id'))
    extra: Mapped[dict | None] = mapped_column(JSON)


class DiagnosticTest(Base):
    __tablename__ = 'diagnostic_tests'
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey('patients.id', ondelete='CASCADE'), index=True)
    name: Mapped[str] = mapped_column(String(120))
    ordered_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    ordered_on: Mapped[date | None] = mapped_column(Date)
    scheduled_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(24))
    completed_on: Mapped[date | None] = mapped_column(Date)
    result_on: Mapped[date | None] = mapped_column(Date)
    reviewed_on: Mapped[date | None] = mapped_column(Date)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    review_note: Mapped[str | None] = mapped_column(Text)
    abnormal: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[str | None] = mapped_column(String(20))
    notes: Mapped[str | None] = mapped_column(Text)
    result_summary: Mapped[str | None] = mapped_column(Text)
    result_source: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[str | None] = mapped_column(String(16))
    source_batch_id: Mapped[str | None] = mapped_column(ForeignKey('ingestion_batches.id'))
    extra: Mapped[dict | None] = mapped_column(JSON)
    values: Mapped[list['TestResultValue']] = relationship(cascade='all, delete-orphan', order_by='TestResultValue.seq')


class TestResultValue(Base):
    __tablename__ = 'test_result_values'
    __test__ = False                         # not a pytest test class
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    test_id: Mapped[str] = mapped_column(ForeignKey('diagnostic_tests.id', ondelete='CASCADE'), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    analyte: Mapped[str | None] = mapped_column(String(120))
    value: Mapped[str | None] = mapped_column(String(60))
    unit: Mapped[str | None] = mapped_column(String(30))
    ref_range: Mapped[str | None] = mapped_column(String(60))
    flag: Mapped[str | None] = mapped_column(String(10))


class Referral(Base):
    __tablename__ = 'referrals'
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey('patients.id', ondelete='CASCADE'), index=True)
    referred_to: Mapped[str | None] = mapped_column(String(160))
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    created_on: Mapped[date | None] = mapped_column(Date)
    referred_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    source_batch_id: Mapped[str | None] = mapped_column(ForeignKey('ingestion_batches.id'))
    extra: Mapped[dict | None] = mapped_column(JSON)


class Prescription(Base):
    __tablename__ = 'prescriptions'
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey('patients.id', ondelete='CASCADE'), index=True)
    drug: Mapped[str | None] = mapped_column(String(200))
    prescribed_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    rx_date: Mapped[date | None] = mapped_column(Date)
    refill_due: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str | None] = mapped_column(String(20))
    source_batch_id: Mapped[str | None] = mapped_column(ForeignKey('ingestion_batches.id'))
    extra: Mapped[dict | None] = mapped_column(JSON)


class Consultation(Base):
    __tablename__ = 'consultations'
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey('patients.id', ondelete='CASCADE'), index=True)
    doctor_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'))
    consult_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    diagnosis: Mapped[str | None] = mapped_column(Text)
    prescription: Mapped[str | None] = mapped_column(Text)
    plan: Mapped[str | None] = mapped_column(Text)
    follow_up: Mapped[date | None] = mapped_column(Date)
    instructions: Mapped[str | None] = mapped_column(Text)
    created_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_batch_id: Mapped[str | None] = mapped_column(ForeignKey('ingestion_batches.id'))
    extra: Mapped[dict | None] = mapped_column(JSON)
