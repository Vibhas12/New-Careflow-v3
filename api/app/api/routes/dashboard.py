"""Role-specific dashboard data (same content as the V2 dashboards), computed on the server within the user's scope."""
from datetime import timedelta

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api import present
from app.api.deps import DB, CurrentUser
from app.api.routes.care_gaps import alerts_out
from app.api.routes.patients import list_items
from app.models import Appointment, AuditLog, CareGapAlert, Consultation, DiagnosticTest, Patient, Task, User
from app.services.care_gaps import RULES
from app.services.common import today

router = APIRouter(prefix='/api/dashboard', tags=['dashboard'])
ACTIVE = ('Scheduled', 'Confirmed')
PENDING = ('Ordered', 'Scheduled', 'Completed')


def _recent(db, ids: set[str], n=6) -> list[dict]:
    out, seen = [], set()
    for a in db.execute(select(AuditLog).where(AuditLog.patient_id.in_(ids), AuditLog.action != 'Viewed patient record')
                        .order_by(AuditLog.ts.desc(), AuditLog.id.desc()).limit(200)).scalars():
        if a.patient_id in seen:
            continue
        seen.add(a.patient_id)
        out.append({'patientId': a.patient_id, 'action': a.action, 'ts': a.ts})
        if len(out) >= n:
            break
    names = present.patient_names(db, [x['patientId'] for x in out])
    return [{**x, 'patientName': names.get(x['patientId'], x['patientId'])} for x in out]


@router.get('')
def dashboard(user: CurrentUser, db: DB):
    T = today()
    if user.role == 'admin':
        return _admin(db, T)
    if user.role == 'doctor':
        return _doctor(db, user, T)
    return _coordinator(db, user, T)


def _coordinator(db, user: User, T):
    mine = list(db.execute(select(Patient).where(Patient.coord_id == user.id, Patient.draft.is_(False), Patient.discharged.is_(False))).scalars())
    ids = {p.id for p in mine}
    appts = list(db.execute(select(Appointment).where(Appointment.patient_id.in_(ids))).scalars())
    tests = list(db.execute(select(DiagnosticTest).where(DiagnosticTest.patient_id.in_(ids), DiagnosticTest.status.in_(PENDING + ('Result Available',)))
                            .order_by(DiagnosticTest.ordered_on.desc())).scalars())
    open_tasks = list(db.execute(select(Task).options(selectinload(Task.events)).where(Task.assignee == user.id, Task.status != 'Completed')).scalars())
    upcoming = [a for a in appts if a.status in ACTIVE and T <= a.appt_date <= T + timedelta(days=7)]
    todays = sorted((a for a in appts if a.appt_date == T and a.status != 'Cancelled'), key=lambda a: a.appt_time or '')
    due = sorted((k for k in open_tasks if k.due and k.due <= T), key=lambda k: k.due)
    results = [t for t in tests if t.status == 'Result Available']
    return {
        'kpis': {'assigned': len(mine), 'high': sum(1 for p in mine if p.priority == 'high'), 'upcoming7': len(upcoming),
                 'pendingTests': len(tests), 'openTasks': len(open_tasks)},
        'patients': list_items(db, sorted(mine, key=lambda p: (p.last_name, p.first_name))),
        'todayAppointments': present.appointments(db, todays),
        'pendingTests': present.tests(db, (results + [t for t in tests if t.status != 'Result Available'])[:6]),
        'recentPatients': _recent(db, ids),
        'tasksDue': present.tasks(db, due[:6]),
    }


def _doctor(db, user: User, T):
    mine = list(db.execute(select(Patient).where(Patient.doctor_id == user.id, Patient.draft.is_(False), Patient.discharged.is_(False))).scalars())
    ids = {p.id for p in mine}
    gaps = list(db.execute(select(CareGapAlert).where(CareGapAlert.patient_id.in_(ids), CareGapAlert.status == 'Open')).scalars())
    rev = [g for g in gaps if g.rule == 'results_review']
    abnormal_ids = set(db.execute(select(DiagnosticTest.id).where(DiagnosticTest.patient_id.in_(ids), DiagnosticTest.abnormal.is_(True))).scalars())
    last_cons = dict(db.execute(select(Consultation.patient_id, func.max(Consultation.consult_date)).where(Consultation.patient_id.in_(ids))
                                .group_by(Consultation.patient_id)).all())
    plan = [{'patientId': p.id, 'patientName': p.full_name,
             'reason': 'New patient – initial plan not yet recorded' if not last_cons.get(p.id) else f'No consultation recorded for {(T - last_cons[p.id]).days} days'}
            for p in mine if (p.care_plan is None or (p.care_plan.plan_text or '') == 'Initial assessment pending') or (last_cons.get(p.id) and (T - last_cons[p.id]).days > 75)]
    todays = list(db.execute(select(Appointment).where(Appointment.doctor_id == user.id, Appointment.appt_date == T, Appointment.status != 'Cancelled')
                             .order_by(Appointment.appt_time)).scalars())
    review_tasks = db.execute(select(func.count()).where(Task.assignee == user.id, Task.kind == 'review', Task.status != 'Completed')).scalar_one()
    return {
        'kpis': {'assigned': len(mine), 'appointmentsToday': len(todays), 'pendingReviews': len(rev) + review_tasks,
                 'followUpsDue': sum(1 for g in gaps if g.rule == 'overdue_followup')},
        'review': {'results': alerts_out(db, rev), 'abnormal': alerts_out(db, [g for g in rev if g.entity in abnormal_ids]),
                   'overdue': alerts_out(db, [g for g in gaps if g.rule == 'overdue_followup']), 'plan': plan,
                   'referrals': alerts_out(db, [g for g in gaps if g.rule == 'referral'])},
        'patients': list_items(db, mine),
        'todayAppointments': present.appointments(db, todays),
    }


def _admin(db, T):
    appts = list(db.execute(select(Appointment).where(Appointment.appt_date >= T - timedelta(days=30), Appointment.appt_date <= T + timedelta(days=7))).scalars())
    open_tasks = list(db.execute(select(Task).where(Task.status != 'Completed')).scalars())
    done = list(db.execute(select(Task).where(Task.status == 'Completed', Task.completed_on >= T - timedelta(days=30))).scalars())
    gaps = list(db.execute(select(CareGapAlert.rule, CareGapAlert.priority).where(CareGapAlert.status == 'Open')).all())
    att = [a for a in appts if T - timedelta(days=30) <= a.appt_date <= T and a.status in ('Completed', 'Missed')]
    team = []
    for u in db.execute(select(User).where(User.role.in_(('coordinator', 'doctor')), User.active.is_(True)).order_by(User.role.desc(), User.name)).scalars():
        o, c = [k for k in open_tasks if k.assignee == u.id], [k for k in done if k.assignee == u.id]
        on_time = sum(1 for k in c if k.due and k.completed_on and k.completed_on <= k.due)
        team.append({'name': u.name, 'role': u.role, 'open': len(o), 'overdue': sum(1 for k in o if k.due and k.due < T), 'completed30': len(c),
                     'onTime': round(on_time * 100 / len(c)) if c else None})
    return {
        'kpis': {'activePatients': db.execute(select(func.count()).where(Patient.discharged.is_(False), Patient.draft.is_(False))).scalar_one(),
                 'appointmentsToday': sum(1 for a in appts if a.appt_date == T and a.status != 'Cancelled'),
                 'highGaps': sum(1 for r, p in gaps if p == 'high'), 'openTasks': len(open_tasks),
                 'overdueTasks': sum(1 for k in open_tasks if k.due and k.due < T)},
        'next7': [{'date': (T + timedelta(days=i)).isoformat(), 'booked': sum(1 for a in appts if a.appt_date == T + timedelta(days=i) and a.status in ACTIVE)}
                  for i in range(7)],
        'gapsByCategory': [{'rule': r, 'category': v[0], 'open': sum(1 for x, _ in gaps if x == r)} for r, v in RULES.items()],
        'team': team,
        'attendance': {'n': len(att), 'rate': round(sum(1 for a in att if a.status == 'Completed') * 100 / len(att)) if att else None},
    }
