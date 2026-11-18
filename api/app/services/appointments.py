"""Appointment workflow: book → (confirm) → complete | miss | cancel, plus reschedule. One function per action.

Rules (server-enforced): only coordinators and doctors book; the patient must be visible to the user; the doctor must be an
active doctor; slots are 30 min between 08:00 and 17:30; no booking in the past; a doctor cannot be double-booked
(checked here and by a partial unique index); terminal states (Completed, Missed, Cancelled) cannot change.
"""
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.catalog import ACTIVE_APPT, APPT_TYPES, SLOTS
from app.models import Appointment, Patient, User
from app.services import messaging as msg
from app.services.access import get_visible_patient
from app.services.common import audit, fail, next_id, today, utcnow, fmt_d

BOOKERS = ('coordinator', 'doctor')


def visible_appointment(db: Session, user: User, appt_id: str) -> Appointment:
    a = db.get(Appointment, appt_id)
    if a is None:
        fail(404, 'Appointment not found')
    if user.role == 'doctor':
        p = db.get(Patient, a.patient_id)
        if a.doctor_id != user.id and p.doctor_id != user.id:
            fail(404, 'Appointment not found')
    return a


def _doctor(db: Session, doctor_id: str) -> User:
    d = db.get(User, doctor_id)
    if d is None or d.role != 'doctor' or not d.active:
        fail(422, 'Choose an active doctor')
    return d


def _check_slot(db: Session, doctor_id: str, d: date, t: str, ignore_id: str | None = None) -> None:
    if t not in SLOTS:
        fail(422, 'Choose a 30-minute slot between 08:00 and 17:30')
    if d < today():
        fail(422, 'Appointments cannot be booked in the past')
    q = select(Appointment.id).where(Appointment.doctor_id == doctor_id, Appointment.appt_date == d, Appointment.appt_time == t,
                                     Appointment.status.in_(ACTIVE_APPT))
    if ignore_id:
        q = q.where(Appointment.id != ignore_id)
    if db.execute(q).first():
        fail(409, 'That slot is already booked for this doctor')


def free_slots(db: Session, doctor_id: str, d: date, ignore_id: str | None = None) -> list[str]:
    taken = set(db.execute(select(Appointment.appt_time).where(Appointment.doctor_id == doctor_id, Appointment.appt_date == d,
                                                               Appointment.status.in_(ACTIVE_APPT), Appointment.id != (ignore_id or ''))).scalars())
    return [s for s in SLOTS if s not in taken]


def _commit(db: Session):
    try:
        db.commit()
    except IntegrityError:                       # lost a race for the same slot
        db.rollback()
        fail(409, 'That slot was just booked by someone else – choose another')


def book(db: Session, user: User, *, patient_id: str, doctor_id: str, d: date, t: str, typ: str, notes: str | None) -> Appointment:
    if user.role not in BOOKERS:
        fail(403, 'Your role cannot book appointments')
    if typ not in APPT_TYPES:
        fail(422, 'Unknown appointment type')
    p = get_visible_patient(db, user, patient_id)
    doc = _doctor(db, doctor_id)
    _check_slot(db, doc.id, d, t)
    a = Appointment(id=next_id(db, 'APT', 5000), patient_id=p.id, doctor_id=doc.id, dept=p.department, appt_date=d, appt_time=t, type=typ,
                    status='Scheduled', created_on=utcnow(), booked_by=user.id, notes=(notes or '').strip() or None)
    db.add(a)
    db.flush()
    n = msg.schedule_appointment_reminders(db, a)
    audit(db, user, 'Appointment booked', patient_id=p.id, entity=a.id, detail=f'{fmt_d(d)} {t} · {typ} · {doc.name} · {n} reminder(s) scheduled')
    msg.notify(db, doc.id, 'Appointment booked', f'{p.first_name} {p.last_name} – {fmt_d(d)} {t}', actor=user, patient_id=p.id, route='appointments')
    _commit(db)
    return a


def _active(a: Appointment):
    if a.status not in ACTIVE_APPT:
        fail(409, f'The appointment is already {a.status.lower()}')


def _append_note(a: Appointment, text: str):
    a.notes = f'{a.notes} | {text}' if a.notes else text


def reschedule(db: Session, user: User, a: Appointment, d: date, t: str, reason: str | None) -> Appointment:
    if user.role not in BOOKERS + ('admin',):
        fail(403, 'Your role cannot reschedule appointments')
    _active(a)
    _check_slot(db, a.doctor_id, d, t, ignore_id=a.id)
    old = f'{fmt_d(a.appt_date)} {a.appt_time}'
    a.appt_date, a.appt_time, a.status = d, t, 'Scheduled'
    _append_note(a, f'Rescheduled from {old}' + (f': {reason.strip()}' if reason and reason.strip() else ''))
    msg.drop_scheduled(db, 'Appointment', a.id)
    db.flush()
    msg.schedule_appointment_reminders(db, a)
    audit(db, user, 'Appointment rescheduled', patient_id=a.patient_id, entity=a.id, detail=f'{old} → {fmt_d(d)} {t}')
    msg.notify(db, a.doctor_id, 'Appointment rescheduled', f'{old} → {fmt_d(d)} {t}', actor=user, patient_id=a.patient_id, route='appointments')
    _commit(db)
    return a


def cancel(db: Session, user: User, a: Appointment, reason: str) -> Appointment:
    _active(a)
    if len((reason or '').strip()) < 3:
        fail(422, 'Give a reason for the cancellation')
    a.status = 'Cancelled'
    _append_note(a, f'Cancelled: {reason.strip()}')
    msg.drop_scheduled(db, 'Appointment', a.id)
    audit(db, user, 'Appointment cancelled', patient_id=a.patient_id, entity=a.id, detail=reason.strip())
    msg.notify(db, a.doctor_id, 'Appointment cancelled', f'{fmt_d(a.appt_date)} {a.appt_time} – {reason.strip()}', actor=user, patient_id=a.patient_id, route='appointments')
    db.commit()
    return a


def confirm(db: Session, user: User, a: Appointment) -> Appointment:
    if a.status != 'Scheduled':
        fail(409, f'Only scheduled appointments can be confirmed (this one is {a.status.lower()})')
    a.status = 'Confirmed'
    msg.mark_latest_reminder_confirmed(db, a.id)
    audit(db, user, 'Appointment confirmed', patient_id=a.patient_id, entity=a.id, detail='Patient confirmation recorded')
    db.commit()
    return a


def complete(db: Session, user: User, a: Appointment) -> Appointment:
    _active(a)
    if a.appt_date > today():
        fail(409, 'A future appointment cannot be marked completed')
    a.status = 'Completed'
    msg.drop_scheduled(db, 'Appointment', a.id)
    audit(db, user, 'Appointment completed', patient_id=a.patient_id, entity=a.id, detail=a.type)
    db.commit()
    return a


def miss(db: Session, user: User, a: Appointment) -> Appointment:
    _active(a)
    if a.appt_date > today():
        fail(409, 'A future appointment cannot be marked missed')
    a.status = 'Missed'
    msg.drop_scheduled(db, 'Appointment', a.id)
    p = db.get(Patient, a.patient_id)
    audit(db, user, 'Appointment marked missed', patient_id=p.id, entity=a.id, detail=f'{fmt_d(a.appt_date)}')
    msg.notify(db, a.doctor_id, 'Patient missed appointment', f'{p.first_name} {p.last_name} did not attend on {fmt_d(a.appt_date)}.',
               actor=user, patient_id=p.id, route=f'patients/{p.id}', level='high')
    db.commit()
    return a
