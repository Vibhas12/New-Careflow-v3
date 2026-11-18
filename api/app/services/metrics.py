"""Operational metrics for Doctor Performance and Executive Overview (multi-agent phase 6) – deterministic code, aggregates only.

These describe coordination workflow (attendance, follow-up timeliness, review turnaround, reminders); they are NOT clinical-quality
rankings. No patient-level data leaves this module: every value is a count, a percentage or an average, with its sample size `n`.
Patient satisfaction and recovery outcomes from V2 are not shown – those features were removed in phase 4.
"""
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.catalog import DEPARTMENTS
from app.models import AgentRun, Appointment, AssistantProposal, CareGapAlert, DiagnosticTest, Patient, Reminder, Task, User
from app.services.common import today

RANGES = {'7': 7, '30': 30, '90': 90, '180': 180, '365': 365, 'all': None}
FOLLOW_KINDS = ('followup', 'contact', 'referral', 'test', 'medication')
DONE_TEST = ('Completed', 'Result Available', 'Reviewed')
MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


def pct(a: int, b: int) -> int | None:
    return round(100 * a / b) if b else None


def _from(range_key: str) -> date:
    days = RANGES.get(range_key, 90)
    return date(2000, 1, 1) if days is None else today() - timedelta(days=days)


def _weeks(start: date) -> list[date]:
    T = today()
    s = max(start, T - timedelta(days=90))
    s -= timedelta(days=s.weekday())
    out = []
    while s <= T:
        out.append(s)
        s += timedelta(days=7)
    return out[-13:]


def _label(d: date) -> str:
    return f'{d.day} {MON[d.month - 1]}'


def metric(key: str, label: str, value, n: int | None, definition: str, unit: str = 'count') -> dict:
    disp = '—' if value is None else (f'{value}%' if unit == '%' else f'{value} days' if unit == 'days' else str(value))
    return {'key': key, 'label': label, 'value': value, 'display': disp, 'unit': unit, 'n': n, 'definition': definition}


def _attendance(appts: list[Appointment]) -> tuple[int | None, int]:
    x = [a for a in appts if a.status in ('Completed', 'Missed')]
    return pct(sum(a.status == 'Completed' for a in x), len(x)), len(x)


def _patients(db: Session, doctor_id: str | None, dept: str | None) -> list[Patient]:
    q = select(Patient).where(Patient.draft.is_(False), Patient.discharged.is_(False))
    if doctor_id:
        q = q.where(Patient.doctor_id == doctor_id)
    if dept:
        q = q.where(Patient.department == dept)
    return list(db.execute(q).scalars())


def performance(db: Session, *, doctor_id: str | None, dept: str | None, range_key: str) -> dict:
    T, start = today(), _from(range_key)
    pats = _patients(db, doctor_id, dept)
    ids = [p.id for p in pats]
    aq = select(Appointment).where(Appointment.appt_date >= start, Appointment.appt_date <= T)
    if doctor_id:
        aq = aq.where(Appointment.doctor_id == doctor_id)
    if dept:
        aq = aq.where(Appointment.dept == dept)
    appts = list(db.execute(aq).scalars())
    tests = list(db.execute(select(DiagnosticTest).where(DiagnosticTest.patient_id.in_(ids))).scalars()) if ids else []
    reviewed = [t for t in tests if t.result_on and t.reviewed_on and t.reviewed_on >= start]
    resp = [(t.reviewed_on - t.result_on).days for t in reviewed]
    tasks = list(db.execute(select(Task).where(Task.patient_id.in_(ids), Task.kind.in_(FOLLOW_KINDS))).scalars()) if ids else []
    done = [k for k in tasks if k.status == 'Completed' and k.completed_on and k.completed_on >= start]
    on_time = [k for k in done if k.due and k.completed_on <= k.due]
    overdue = [k for k in tasks if k.status != 'Completed' and k.due and k.due < T]
    rem = list(db.execute(select(Reminder).where(Reminder.patient_id.in_(ids), Reminder.status != 'Scheduled')).scalars()) if ids else []
    good = [r for r in rem if r.status in ('Delivered', 'Confirmed')]
    att, att_n = _attendance(appts)
    kpis = [
        metric('patients_managed', 'Patients managed', len(pats), len(pats), 'Active patients assigned (in the selected department).'),
        metric('completed_consultations', 'Completed consultations', sum(a.status == 'Completed' for a in appts), len(appts),
               'Appointments with status Completed in the date range.'),
        metric('pending_reviews', 'Pending reviews', sum(t.status == 'Result Available' for t in tests), len(tests),
               'Diagnostic results available and not yet reviewed (now).'),
        metric('avg_review_days', 'Average review turnaround', round(sum(resp) / len(resp), 1) if resp else None, len(resp),
               'Days from result available to doctor review, for results reviewed in the range.', 'days'),
        metric('attendance', 'Appointment attendance', att, att_n, 'Completed ÷ (completed + missed) appointments in the range.', '%'),
        metric('followup_compliance', 'Follow-up compliance', pct(len(on_time), len(done) + len(overdue)), len(done) + len(overdue),
               'Follow-up tasks completed by their due date ÷ (completed in range + currently overdue).', '%'),
        metric('reminder_success', 'Reminder success rate', pct(len(good), len(rem)), len(rem), 'Simulated reminders delivered or confirmed.', '%'),
    ]
    wk = _weeks(start)
    in_w = lambda d, w: d is not None and w <= d < w + timedelta(days=7)
    weekly = {'labels': [_label(w) for w in wk], 'series': {
        'Attendance %': [_attendance([a for a in appts if in_w(a.appt_date, w)])[0] for w in wk],
        'Completed': [sum(a.status == 'Completed' and in_w(a.appt_date, w) for a in appts) for w in wk],
        'Missed': [sum(a.status == 'Missed' and in_w(a.appt_date, w) for a in appts) for w in wk],
        'Cancelled': [sum(a.status == 'Cancelled' and in_w(a.appt_date, w) for a in appts) for w in wk],
        'Follow-ups created': [sum(in_w(k.created, w) for k in tasks) for w in wk],
        'Follow-ups completed': [sum(in_w(k.completed_on, w) for k in tasks) for w in wk],
        'Tests ordered': [sum(in_w(t.ordered_on, w) for t in tests) for w in wk],
    }}
    return {'range': range_key, 'from': start.isoformat() if RANGES.get(range_key, 90) else None, 'kpis': kpis, 'weekly': weekly}


def executive(db: Session, *, range_key: str) -> dict:
    T, start = today(), _from(range_key)
    pats = _patients(db, None, None)
    dept_of = {p.id: p.department for p in pats}
    appts = list(db.execute(select(Appointment).where(Appointment.appt_date >= start, Appointment.appt_date <= T)).scalars())
    tests = list(db.execute(select(DiagnosticTest).where(DiagnosticTest.ordered_on >= start)).scalars())
    tasks_done = list(db.execute(select(Task).where(Task.status == 'Completed', Task.completed_on >= start)).scalars())
    fu = list(db.execute(select(Task).where(Task.kind.in_(('followup', 'contact')), Task.due >= start, Task.due <= T)).scalars())
    rem = list(db.execute(select(Reminder).where(Reminder.status != 'Scheduled')).scalars())
    gaps = list(db.execute(select(CareGapAlert).where(CareGapAlert.status == 'Open')).scalars())
    att, att_n = _attendance(appts)
    tc = [t for t in tests if t.status in DONE_TEST]
    kpis = [
        metric('followup_completion', 'Follow-up completion', pct(sum(k.status == 'Completed' for k in fu), len(fu)), len(fu),
               'Follow-up / contact tasks due in the range that are complete.', '%'),
        metric('attendance', 'Appointment attendance', att, att_n, 'Completed ÷ (completed + missed) appointments in the range.', '%'),
        metric('test_completion', 'Diagnostic test completion', pct(len(tc), len(tests)), len(tests), 'Tests ordered in the range that were completed.', '%'),
        metric('tasks_completed', 'Tasks completed', len(tasks_done), len(tasks_done), 'Tasks completed in the range.'),
        metric('patients_supported', 'Patients supported', len(pats), len(pats), 'Active patients (now).'),
        metric('open_care_gaps', 'Outstanding care gaps', len(gaps), len(gaps), 'Open care-gap alerts (now).'),
        metric('missed_appointments', 'Missed appointments', sum(a.status == 'Missed' for a in appts), len(appts), 'Appointments marked Missed in the range.'),
        metric('reminder_effectiveness', 'Reminder effectiveness', pct(sum(r.status in ('Delivered', 'Confirmed') for r in rem), len(rem)), len(rem),
               'Simulated reminders delivered or confirmed.', '%'),
    ]
    wk = _weeks(start)
    in_w = lambda d, w: d is not None and w <= d < w + timedelta(days=7)
    weekly = {'labels': [_label(w) for w in wk], 'series': {
        'Attendance %': [_attendance([a for a in appts if in_w(a.appt_date, w)])[0] for w in wk],
        'Tasks completed': [sum(in_w(k.completed_on, w) for k in tasks_done) for w in wk],
    }}
    depts = []
    for d in DEPARTMENTS:
        a_d = [a for a in appts if (a.dept or dept_of.get(a.patient_id)) == d]
        t_d = [t for t in tests if dept_of.get(t.patient_id) == d]
        f_d = [k for k in fu if k.patient_id and dept_of.get(k.patient_id) == d]
        a_rate, a_n = _attendance(a_d)
        depts.append({'department': d, 'attendance': a_rate, 'attendanceN': a_n, 'testCompletion': pct(sum(t.status in DONE_TEST for t in t_d), len(t_d)),
                      'testN': len(t_d), 'followupCompletion': pct(sum(k.status == 'Completed' for k in f_d), len(f_d)), 'followupN': len(f_d),
                      'openGaps': sum(dept_of.get(g.patient_id) == d for g in gaps)})
    runs = dict(((a, s), n) for a, s, n in db.execute(select(AgentRun.agent, AgentRun.status, func.count()).where(AgentRun.created_at >= start)
                                                      .group_by(AgentRun.agent, AgentRun.status)).all())
    usage = [
        {'label': 'AI outputs accepted by the checks', 'value': sum(n for (a, s), n in runs.items() if s == 'ok')},
        {'label': 'AI outputs withheld by the checks', 'value': sum(n for (a, s), n in runs.items() if s == 'withheld')},
        {'label': 'AI-drafted actions approved', 'value': db.execute(select(func.count()).select_from(AssistantProposal)
                                                                    .where(AssistantProposal.status == 'Approved')).scalar() or 0},
    ]
    return {'range': range_key, 'from': start.isoformat() if RANGES.get(range_key, 90) else None, 'kpis': kpis, 'weekly': weekly,
            'departments': depts, 'aiUsage': usage}


def doctors(db: Session) -> list[dict]:
    return [{'id': i, 'name': n} for i, n in db.execute(select(User.id, User.name).where(User.role == 'doctor', User.active.is_(True)).order_by(User.name)).all()]
