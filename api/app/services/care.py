"""Referrals and consultations (with doctor-entered prescriptions and follow-up tasks)."""
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models import CarePlan, Consultation, Prescription, Referral, User
from app.services import tasks as task_svc
from app.services.access import get_visible_patient
from app.services.common import audit, fail, next_id, today, utcnow, fmt_d

REFERRAL_FLOW = {'Pending': {'Booked', 'Cancelled'}, 'Booked': {'Completed', 'Cancelled'}, 'Completed': set(), 'Cancelled': set()}


def create_referral(db: Session, user: User, patient_id: str, to: str, reason: str) -> Referral:
    if user.role not in ('coordinator', 'doctor'):
        fail(403, 'Your role cannot create referrals')
    p = get_visible_patient(db, user, patient_id)
    r = Referral(id=next_id(db, 'REF', 2000), patient_id=p.id, referred_to=to.strip(), reason=reason.strip(), status='Pending',
                 created_on=today(), referred_by=user.id)
    db.add(r)
    db.flush()
    audit(db, user, 'Referral created', patient_id=p.id, entity=r.id, detail=r.referred_to)
    db.commit()
    return r


def set_referral_status(db: Session, user: User, ref_id: str, status: str) -> Referral:
    if user.role not in ('coordinator', 'doctor'):
        fail(403, 'Your role cannot update referrals')
    r = db.get(Referral, ref_id)
    if r is None:
        fail(404, 'Referral not found')
    get_visible_patient(db, user, r.patient_id)
    if status not in REFERRAL_FLOW.get(r.status, set()):
        fail(409, f'A {r.status.lower()} referral cannot become {status.lower()}')
    old, r.status = r.status, status
    audit(db, user, f'Referral {status.lower()}', patient_id=r.patient_id, entity=r.id, detail=f'{r.referred_to}: {old} → {status}')
    db.commit()
    return r


def record_consultation(db: Session, user: User, patient_id: str, *, d: date, notes: str, diagnosis: str | None, prescription: str | None,
                        plan: str | None, follow_up: date | None, instructions: str | None, create_follow_up_task: bool) -> Consultation:
    if user.role != 'doctor':
        fail(403, 'Only doctors can record consultations')
    p = get_visible_patient(db, user, patient_id)
    if p.doctor_id != user.id:
        fail(403, 'Doctors can record consultations only for their own patients')
    if d > today():
        fail(422, 'The consultation date cannot be in the future')
    if follow_up and follow_up <= d:
        fail(422, 'The follow-up date must be after the consultation date')
    clean = lambda s: (s or '').strip() or None
    c = Consultation(id=next_id(db, 'CON', 4000), patient_id=p.id, doctor_id=user.id, consult_date=d, notes=notes.strip(), diagnosis=clean(diagnosis),
                     prescription=clean(prescription), plan=clean(plan), follow_up=follow_up, instructions=clean(instructions), created_on=utcnow())
    db.add(c)
    db.flush()
    if c.plan:
        if p.care_plan:
            p.care_plan.plan_text = c.plan
        else:
            p.care_plan = CarePlan(plan_text=c.plan, start_date=d)
    if follow_up:
        p.review_due = follow_up
    if c.prescription:
        db.add(Prescription(id=next_id(db, 'RX', 1000), patient_id=p.id, drug=c.prescription, prescribed_by=user.id, rx_date=d,
                            refill_due=d + timedelta(days=28), status='Active', extra={'doctorEntered': True}))
        audit(db, user, 'Prescription recorded (doctor-entered)', patient_id=p.id, entity=c.id, detail=c.prescription)
    audit(db, user, 'Consultation notes saved', patient_id=p.id, entity=c.id,
          detail=' · '.join(x for x in [f'Dx: {c.diagnosis}' if c.diagnosis else '', f'follow-up {fmt_d(follow_up)}' if follow_up else ''] if x))
    if create_follow_up_task and follow_up and p.coord_id:
        task_svc.create(db, user, title=f'Arrange follow-up appointment for {fmt_d(follow_up)}', patient_id=p.id, priority='med', assignee=p.coord_id,
                        due=max(today(), follow_up - timedelta(days=3)), kind='followup', source='Doctor consultation',
                        description=f'Requested by {user.name}.' + (f' Instructions: {c.instructions}' if c.instructions else ''), commit=False)
    db.commit()
    return c
