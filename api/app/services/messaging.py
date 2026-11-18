"""In-app notifications and appointment/test reminders.

Nothing is delivered to a real phone or inbox – reminders are simulated. They are created and withdrawn here as
appointments/tests change; the scheduler (app/jobs.py) marks due reminders as delivered.
"""
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import AppSetting, Notification, Patient, Reminder, User
from app.services.common import next_id, utcnow, fmt_d

APPT_OFFSETS = {'7d': timedelta(days=7), '3d': timedelta(days=3), '1d': timedelta(days=1), '2h': timedelta(hours=2)}
TEST_OFFSETS = {'1d': timedelta(days=1), '2h': timedelta(hours=2)}


def notify(db: Session, to_user: str | None, title: str, text: str, *, actor: User | None = None, patient_id: str | None = None,
           route: str | None = None, level: str = 'info') -> None:
    """Never notify people about their own actions."""
    if not to_user or (actor and actor.id == to_user):
        return
    db.add(Notification(id=next_id(db, 'NTF', 1000), ts=utcnow(), to_user=to_user, title=title, text=text, route=route,
                        patient_id=patient_id, is_read=False, level=level))


def send_manual_reminder(db: Session, user: User, patient: Patient, *, kind: str, label: str, channel: str, message: str,
                         ref_id: str | None = None) -> Reminder:
    """A reminder sent now by a person (or an approved AI proposal). SIMULATED: recorded as Delivered/Failed, nothing is sent."""
    from app.jobs import _simulated_outcome
    from app.services.common import audit
    rid, now = next_id(db, 'REM', 1000), utcnow()
    r = Reminder(id=rid, kind=kind, ref_id=ref_id, patient_id=patient.id, offset_label='manual', channel=channel, scheduled_for=now,
                 status=_simulated_outcome(rid), sent_at=now, label=label, message=message.strip(), simulated=True)
    db.add(r)
    audit(db, user, 'Reminder sent (simulated)', patient_id=patient.id, entity=rid, detail=f'{channel} · {message.strip()[:70]}')
    return r


def _reminder_cfg(db: Session) -> tuple[dict, list[str]]:
    s = db.get(AppSetting, 'settings')
    cfg = (s.value if s else {}).get('reminders') or {}
    offsets = cfg.get('offsets') or {k: True for k in APPT_OFFSETS}
    channels = [c for c, on in (cfg.get('channels') or {'SMS': True}).items() if on]
    return offsets, channels


def _at(d: date, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(':'))
    return datetime.combine(d, time(h, m), tzinfo=timezone.utc)


def schedule_appointment_reminders(db: Session, appt) -> int:
    offsets, channels = _reminder_cfg(db)
    if not channels:
        return 0
    when, now, n = _at(appt.appt_date, appt.appt_time or '09:00'), utcnow(), 0
    for i, (label, delta) in enumerate((k, v) for k, v in APPT_OFFSETS.items() if offsets.get(k)):
        at = when - delta
        if at < now:
            continue
        db.add(Reminder(id=next_id(db, 'REM', 1000), kind='Appointment', ref_id=appt.id, patient_id=appt.patient_id, offset_label=label,
                        channel=channels[i % len(channels)], scheduled_for=at, status='Scheduled', label=f'Appointment reminder ({label} before)',
                        message=f'Reminder: appointment on {fmt_d(appt.appt_date)} at {appt.appt_time}.', simulated=True))
        n += 1
    return n


def schedule_test_reminders(db: Session, test) -> int:
    _, channels = _reminder_cfg(db)
    drop_scheduled(db, 'Diagnostic Test', test.id)
    if not channels or not test.scheduled_date:
        return 0
    when, now, n = _at(test.scheduled_date, '08:00'), utcnow(), 0
    for i, (label, delta) in enumerate(TEST_OFFSETS.items()):
        at = when - delta
        if at < now:
            continue
        db.add(Reminder(id=next_id(db, 'REM', 1000), kind='Diagnostic Test', ref_id=test.id, patient_id=test.patient_id, offset_label=label,
                        channel=channels[i % len(channels)], scheduled_for=at, status='Scheduled', label=f'{test.name} reminder ({label} before)',
                        message=f'{test.name} scheduled on {fmt_d(test.scheduled_date)}. Please attend as arranged.', simulated=True))
        n += 1
    return n


def drop_scheduled(db: Session, kind: str, ref_id: str) -> None:
    db.execute(delete(Reminder).where(Reminder.kind == kind, Reminder.ref_id == ref_id, Reminder.status == 'Scheduled'))


def mark_latest_reminder_confirmed(db: Session, appt_id: str) -> None:
    r = db.execute(select(Reminder).where(Reminder.ref_id == appt_id, Reminder.status.in_(('Delivered', 'Sent'))).order_by(Reminder.id.desc())).scalars().first()
    if r:
        r.status = 'Confirmed'


def patient_label(p: Patient) -> str:
    return f'{p.first_name} {p.last_name} ({p.id})'
