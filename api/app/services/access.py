"""Who may see which patient – applied inside database queries, so data a user may not see never leaves the server.

  coordinator → all active (non-draft) patients
  doctor      → only patients assigned to them
  admin       → no patient-level clinical data (operational dashboards use aggregates)
"""
from fastapi import HTTPException, status
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models import Patient, User

CLINICAL_ROLES = ('coordinator', 'doctor')


def scope_patients(stmt: Select, user: User) -> Select:
    if user.role == 'coordinator':
        return stmt.where(Patient.draft.is_(False))
    if user.role == 'doctor':
        return stmt.where(Patient.draft.is_(False), Patient.doctor_id == user.id)
    raise HTTPException(status.HTTP_403_FORBIDDEN, 'Your role does not have access to patient records')


def get_visible_patient(db: Session, user: User, patient_id: str) -> Patient:
    """404 (not 403) when the patient exists but is outside the user's scope, so IDs cannot be probed."""
    p = db.execute(scope_patients(select(Patient), user).where(Patient.id == patient_id)).scalar_one_or_none()
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Patient not found')
    return p
