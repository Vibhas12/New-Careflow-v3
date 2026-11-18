"""Diagnostic test workflow: Ordered → Scheduled → Completed → Result Available → Reviewed.

  request   doctor (own patient)      creates a "Schedule …" task for the patient's coordinator
  schedule  coordinator               date today or later; closes the linked scheduling task; schedules reminders
  complete  coordinator               patient attended; notifies the requesting doctor
  result    coordinator or doctor     SIMULATED result feed (demo only); abnormal results notify the doctor at high level
  review    doctor (own patient)      records the review note
"""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.catalog import TEST_TYPES, simulated_result
from app.models import DiagnosticTest, Patient, Task, TestResultValue, User
from app.services import messaging as msg
from app.services import tasks as task_svc
from app.services.access import get_visible_patient
from app.services.common import audit, fail, next_id, today, fmt_d


def visible_test(db: Session, user: User, test_id: str) -> DiagnosticTest:
    t = db.get(DiagnosticTest, test_id)
    if t is None:
        fail(404, 'Test not found')
    get_visible_patient(db, user, t.patient_id)          # 404 if outside the user's scope (admin → 403)
    return t


def _need(user: User, *roles: str, action: str):
    if user.role not in roles:
        fail(403, f'Your role cannot {action}')


def _status(t: DiagnosticTest, *allowed: str, action: str):
    if t.status not in allowed:
        fail(409, f'Cannot {action}: the test is {t.status}')


def request(db: Session, user: User, *, patient_id: str, name: str, priority: str, notes: str | None) -> DiagnosticTest:
    _need(user, 'doctor', action='request diagnostic tests')
    if name not in TEST_TYPES:
        fail(422, 'Unknown test type')
    p = get_visible_patient(db, user, patient_id)
    if p.doctor_id != user.id:
        fail(403, 'Doctors can request tests only for their own patients')
    t = DiagnosticTest(id=next_id(db, 'TST', 3000), patient_id=p.id, name=name, ordered_by=user.id, ordered_on=today(), status='Ordered',
                       abnormal=False, priority=priority, notes=(notes or '').strip() or None)
    db.add(t)
    db.flush()
    audit(db, user, 'Diagnostic test requested', patient_id=p.id, entity=t.id, detail=f'{name} ({priority})')
    urgent = priority == 'Urgent'
    task_svc.create(db, user, title=f'Schedule {name} for {p.first_name} {p.last_name}', patient_id=p.id, priority='high' if urgent else 'med',
                    assignee=p.coord_id, due=today() + timedelta(days=1 if urgent else 3), kind='test', source='Doctor test request',
                    description=f'Requested by {user.name}' + (f'. Notes: {t.notes}' if t.notes else ''), test_id=t.id, commit=False)
    msg.notify(db, p.coord_id, 'Test requested – task created', f'{name} for {p.first_name} {p.last_name}', actor=user, patient_id=p.id,
               route='tasks', level='high' if urgent else 'info')
    db.commit()
    return t


def schedule(db: Session, user: User, t: DiagnosticTest, d: date) -> DiagnosticTest:
    _need(user, 'coordinator', action='schedule diagnostic tests')
    _status(t, 'Ordered', 'Scheduled', action='schedule')
    if d < today():
        fail(422, 'The test date cannot be in the past')
    t.scheduled_date, t.status = d, 'Scheduled'
    n = msg.schedule_test_reminders(db, t)
    # close the "Schedule <test>" task created by the request
    for k in db.execute(select(Task).where(Task.test_id == t.id, Task.status != 'Completed')).scalars():
        task_svc.apply(db, user, k, status='Completed', note=f'Test scheduled for {fmt_d(d)}', commit=False)
    audit(db, user, 'Diagnostic test scheduled', patient_id=t.patient_id, entity=t.id, detail=f'{t.name} on {fmt_d(d)} · {n} reminder(s)')
    db.commit()
    return t


def complete(db: Session, user: User, t: DiagnosticTest) -> DiagnosticTest:
    _need(user, 'coordinator', action='mark tests completed')
    _status(t, 'Scheduled', action='mark completed')
    t.status, t.completed_on = 'Completed', today()
    msg.drop_scheduled(db, 'Diagnostic Test', t.id)
    p = db.get(Patient, t.patient_id)
    audit(db, user, 'Patient completed test', patient_id=p.id, entity=t.id, detail=t.name)
    msg.notify(db, t.ordered_by, 'Patient completed test', f'{t.name} – {msg.patient_label(p)}. Result pending.', actor=user, patient_id=p.id, route='tests')
    db.commit()
    return t


def record_simulated_result(db: Session, user: User, t: DiagnosticTest, abnormal: bool) -> DiagnosticTest:
    _need(user, 'coordinator', 'doctor', action='record results')
    _status(t, 'Completed', action='record a result')
    r = simulated_result(t.name, abnormal)
    t.status, t.result_on, t.abnormal, t.result_summary, t.result_source = 'Result Available', today(), abnormal, r['summary'], r['source']
    t.values = [TestResultValue(seq=i, **v) for i, v in enumerate(r['values'])]
    p = db.get(Patient, t.patient_id)
    audit(db, user, 'Result received (simulated feed)', patient_id=p.id, entity=t.id, detail=t.name + (' – values outside reference range' if abnormal else ''))
    msg.notify(db, t.ordered_by, 'Abnormal result flagged for review' if abnormal else 'Diagnostic result available', f'{t.name} – {msg.patient_label(p)}',
               actor=user, patient_id=p.id, route='tests', level='high' if abnormal else 'info')
    db.commit()
    return t


def review(db: Session, user: User, t: DiagnosticTest, note: str | None) -> DiagnosticTest:
    _need(user, 'doctor', action='review results')
    p = db.get(Patient, t.patient_id)
    if p.doctor_id != user.id and t.ordered_by != user.id:
        fail(403, 'Only the patient’s doctor or the requesting doctor can review this result')
    _status(t, 'Result Available', action='review')
    t.status, t.reviewed_on, t.reviewed_by, t.review_note = 'Reviewed', today(), user.id, (note or '').strip() or None
    audit(db, user, 'Result reviewed by doctor', patient_id=p.id, entity=t.id, detail=t.name + (f' – {t.review_note}' if t.review_note else ''))
    db.commit()
    return t
