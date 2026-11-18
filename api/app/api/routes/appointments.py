"""Appointments: calendar/list queries, free slots, and one endpoint per workflow action."""
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Query
from sqlalchemy import func, or_, select

from app.api import present
from app.api.deps import DB, CurrentUser
from app.models import Appointment, Patient, Reminder, User
from app.schemas import AppointmentItem, AppointmentPage, BookAppointmentIn, ReasonIn, RescheduleIn, Slots
from app.services import appointments as svc
from app.services.care_gaps import rescan
from app.services.common import fail

router = APIRouter(prefix='/api/appointments', tags=['appointments'])
Status = Literal['Scheduled', 'Confirmed', 'Completed', 'Missed', 'Cancelled']


@router.get('', response_model=AppointmentPage)
def list_appointments(user: CurrentUser, db: DB, date_from: date | None = Query(None, alias='from'), date_to: date | None = Query(None, alias='to'),
                      doctor_id: str | None = Query(None, alias='doctorId'), status: Status | None = None, patient_id: str | None = Query(None, alias='patientId'),
                      limit: int = Query(500, ge=1, le=1000)):
    """Coordinators and administrators: all appointments. Doctors: their own diary and their patients' appointments."""
    if date_from and date_to and date_to < date_from:
        fail(422, '"to" must not be before "from"')
    if date_from and date_to and (date_to - date_from) > timedelta(days=370):
        fail(422, 'Date range is limited to one year')
    q = select(Appointment)
    if user.role == 'doctor':
        q = q.where(or_(Appointment.doctor_id == user.id, Appointment.patient_id.in_(select(Patient.id).where(Patient.doctor_id == user.id))))
    if date_from:
        q = q.where(Appointment.appt_date >= date_from)
    if date_to:
        q = q.where(Appointment.appt_date <= date_to)
    if doctor_id:
        q = q.where(Appointment.doctor_id == doctor_id)
    if status:
        q = q.where(Appointment.status == status)
    if patient_id:
        q = q.where(Appointment.patient_id == patient_id)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = list(db.execute(q.order_by(Appointment.appt_date, Appointment.appt_time).limit(limit)).scalars())
    return AppointmentPage(items=present.appointments(db, rows), total=total)


@router.get('/slots', response_model=Slots)
def slots(user: CurrentUser, db: DB, doctor_id: str = Query(alias='doctorId'), on: date = Query(alias='date'), ignore: str | None = None):
    d = db.get(User, doctor_id)
    if d is None or d.role != 'doctor':
        fail(404, 'Doctor not found')
    return Slots(doctor_id=doctor_id, date=on, slots=svc.free_slots(db, doctor_id, on, ignore))


@router.get('/{appt_id}')
def get_appointment(appt_id: str, user: CurrentUser, db: DB):
    """One appointment with its reminders (the appointment dialog)."""
    a = svc.visible_appointment(db, user, appt_id)
    rem = [] if user.role == 'admin' else [{'id': r.id, 'label': r.label, 'channel': r.channel, 'status': r.status, 'scheduledFor': r.scheduled_for,
                                            'sentAt': r.sent_at} for r in db.execute(select(Reminder).where(Reminder.ref_id == a.id).order_by(Reminder.scheduled_for)).scalars()]
    return {**present.appointment(db, a).model_dump(by_alias=True), 'reminders': rem}


@router.post('', response_model=AppointmentItem, status_code=201)
def book(body: BookAppointmentIn, user: CurrentUser, db: DB):
    a = svc.book(db, user, patient_id=body.patient_id, doctor_id=body.doctor_id, d=body.date, t=body.time, typ=body.type, notes=body.notes)
    rescan(db, [a.patient_id])
    return present.appointment(db, a)


@router.post('/{appt_id}/reschedule', response_model=AppointmentItem)
def reschedule(appt_id: str, body: RescheduleIn, user: CurrentUser, db: DB):
    a = svc.reschedule(db, user, svc.visible_appointment(db, user, appt_id), body.date, body.time, body.reason)
    rescan(db, [a.patient_id])
    return present.appointment(db, a)


@router.post('/{appt_id}/cancel', response_model=AppointmentItem)
def cancel(appt_id: str, body: ReasonIn, user: CurrentUser, db: DB):
    a = svc.cancel(db, user, svc.visible_appointment(db, user, appt_id), body.reason)
    rescan(db, [a.patient_id])
    return present.appointment(db, a)


@router.post('/{appt_id}/{action}', response_model=AppointmentItem)
def transition(appt_id: str, action: Literal['confirm', 'complete', 'miss'], user: CurrentUser, db: DB):
    a = svc.visible_appointment(db, user, appt_id)
    a = {'confirm': svc.confirm, 'complete': svc.complete, 'miss': svc.miss}[action](db, user, a)
    rescan(db, [a.patient_id])
    return present.appointment(db, a)
