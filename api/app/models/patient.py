"""Patients and their directly owned lists (allergies, medications, diagnoses, care plan, history)."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

PRIORITIES = ('high', 'med', 'low')


class Patient(Base):
    __tablename__ = 'patients'
    __table_args__ = (CheckConstraint("priority IN ('high','med','low')", name='priority'),
                      Index('ix_patients_name', 'last_name', 'first_name'))
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    dob: Mapped[date | None] = mapped_column(Date)
    gender: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(254))
    mobile: Mapped[str | None] = mapped_column(String(40))
    address: Mapped[str | None] = mapped_column(Text)
    ec_name: Mapped[str | None] = mapped_column(String(120))
    ec_phone: Mapped[str | None] = mapped_column(String(40))
    department: Mapped[str | None] = mapped_column(ForeignKey('departments.name'))
    primary_condition: Mapped[str | None] = mapped_column(Text)
    secondary_conditions: Mapped[str | None] = mapped_column(Text)
    previous_surgeries: Mapped[str | None] = mapped_column(Text)
    family_history: Mapped[str | None] = mapped_column(Text)
    ins_provider: Mapped[str | None] = mapped_column(String(80))
    policy: Mapped[str | None] = mapped_column(String(80))
    coverage: Mapped[str | None] = mapped_column(String(80))
    doctor_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'), index=True)
    coord_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'), index=True)
    registered_on: Mapped[date | None] = mapped_column(Date)
    review_due: Mapped[date | None] = mapped_column(Date)
    plan_review_due: Mapped[date | None] = mapped_column(Date)
    discharged: Mapped[bool] = mapped_column(Boolean, default=False)
    draft: Mapped[bool] = mapped_column(Boolean, default=False)
    # Current priority. Changed ONLY through services.priority (every change is appended to priority_history).
    priority: Mapped[str] = mapped_column(String(4), default='med')
    priority_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_batch_id: Mapped[str | None] = mapped_column(ForeignKey('ingestion_batches.id'))
    extra: Mapped[dict | None] = mapped_column(JSON)

    allergies: Mapped[list['Allergy']] = relationship(cascade='all, delete-orphan', order_by='Allergy.id')
    medications: Mapped[list['Medication']] = relationship(cascade='all, delete-orphan', order_by='Medication.id')
    diagnoses: Mapped[list['Diagnosis']] = relationship(cascade='all, delete-orphan', order_by='Diagnosis.id')
    care_plan: Mapped['CarePlan | None'] = relationship(cascade='all, delete-orphan', uselist=False)

    @property
    def full_name(self) -> str:
        return f'{self.first_name} {self.last_name}'


class _PatientList:
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_batch_id: Mapped[str | None] = mapped_column(ForeignKey('ingestion_batches.id'))


class Allergy(_PatientList, Base):
    __tablename__ = 'allergies'
    __table_args__ = (UniqueConstraint('patient_id', 'substance'),)
    patient_id: Mapped[str] = mapped_column(ForeignKey('patients.id', ondelete='CASCADE'), index=True)
    substance: Mapped[str] = mapped_column(String(200))


class Medication(_PatientList, Base):
    __tablename__ = 'medications'
    __table_args__ = (UniqueConstraint('patient_id', 'description'),)
    patient_id: Mapped[str] = mapped_column(ForeignKey('patients.id', ondelete='CASCADE'), index=True)
    description: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default='Active')


class Diagnosis(_PatientList, Base):
    __tablename__ = 'diagnoses'
    __table_args__ = (UniqueConstraint('patient_id', 'description'),)
    patient_id: Mapped[str] = mapped_column(ForeignKey('patients.id', ondelete='CASCADE'), index=True)
    description: Mapped[str] = mapped_column(String(300))


class CarePlan(_PatientList, Base):
    __tablename__ = 'care_plans'
    patient_id: Mapped[str] = mapped_column(ForeignKey('patients.id', ondelete='CASCADE'), unique=True)
    plan_text: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[date | None] = mapped_column(Date)


class MedicalHistory(Base):
    __tablename__ = 'medical_history'
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey('patients.id', ondelete='CASCADE'), index=True)
    event_date: Mapped[date | None] = mapped_column(Date)
    type: Mapped[str | None] = mapped_column(String(40))
    title: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)
    source_batch_id: Mapped[str | None] = mapped_column(ForeignKey('ingestion_batches.id'))
