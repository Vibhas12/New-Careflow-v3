"""Auditable patient priority. The only code path that changes patients.priority.

Rules: Care Coordinator (any visible patient) and Doctor (own patients) only; mandatory comment; every change is appended
to priority_history (append-only, enforced by database triggers); care-gap rules and the AI may only *suggest*.
"""
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Patient, PriorityHistory, User
from app.services.access import get_visible_patient
from app.services.common import audit, utcnow

LEVELS = ('high', 'med', 'low')
LABEL = {'high': 'High', 'med': 'Medium', 'low': 'Low'}
MIN_COMMENT = 5


def record_initial(db: Session, patient: Patient, actor_name: str, actor_role: str, comment: str, actor_id: str | None = None) -> None:
    db.add(PriorityHistory(patient_id=patient.id, previous_priority=None, new_priority=patient.priority, comment=comment,
                           user_id=actor_id, user_name=actor_name, user_role=actor_role, changed_at=utcnow()))


def change_priority(db: Session, user: User, patient_id: str, new: str, comment: str, ip: str | None = None) -> PriorityHistory:
    if user.role not in ('coordinator', 'doctor'):
        raise HTTPException(status.HTTP_403_FORBIDDEN, 'Your role is not authorised to change patient priority')
    comment = (comment or '').strip()
    if len(comment) < MIN_COMMENT:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f'A comment explaining the reason is mandatory (at least {MIN_COMMENT} characters)')
    p = get_visible_patient(db, user, patient_id)           # doctors: own patients only (others → 404)
    # lock the row so two simultaneous changes cannot both read the same "previous" value
    p = db.execute(select(Patient).where(Patient.id == p.id).with_for_update()).scalar_one()
    if p.priority == new:
        raise HTTPException(status.HTTP_409_CONFLICT, 'The new priority is the same as the current priority')
    old, now = p.priority, utcnow()
    p.priority, p.priority_updated_at = new, now
    entry = PriorityHistory(patient_id=p.id, previous_priority=old, new_priority=new, comment=comment,
                            user_id=user.id, user_name=user.name, user_role=user.role, changed_at=now)
    db.add(entry)
    db.flush()
    audit(db, user, 'Patient priority changed', patient_id=p.id, entity=f'PRI-{entry.id}', detail=f'{LABEL[old]} → {LABEL[new]}: {comment}', ip=ip)
    db.commit()
    return entry


def history(db: Session, user: User, patient_id: str) -> list[PriorityHistory]:
    get_visible_patient(db, user, patient_id)
    return list(db.execute(select(PriorityHistory).where(PriorityHistory.patient_id == patient_id).order_by(PriorityHistory.id)).scalars())
