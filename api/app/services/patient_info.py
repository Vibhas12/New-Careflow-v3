"""Derived per-patient facts shown across the UI (same definitions as the V2 prototype), computed in batches.

  last_visit        latest completed appointment, or a recorded consultation up to today
  next_appt         earliest Scheduled/Confirmed appointment from today
  status            Discharged · Awaiting results · Under follow-up · Active
  follow_up_status  Follow-up overdue · Follow-up scheduled · No follow-up scheduled · Discharged – none required
  attention         first open care gap ("<category> – <reason>"), or an alert being actioned
"""
from collections import defaultdict
from datetime import date

from sqlalchemy import case, exists, or_, select
from sqlalchemy.orm import Session

from app.models import Appointment, CareGapAlert, Consultation, DiagnosticTest, Patient
from app.services.care_gaps import PRI_RANK
from app.services.common import today

PENDING_TESTS = ('Ordered', 'Scheduled', 'Completed', 'Result Available')
ACTIVE = ('Scheduled', 'Confirmed')


def status_expr():
    """SQL expression equal to the computed status – used for filtering in the database."""
    awaiting = exists().where(DiagnosticTest.patient_id == Patient.id, DiagnosticTest.status.in_(PENDING_TESTS))
    upcoming = exists().where(Appointment.patient_id == Patient.id, Appointment.status.in_(ACTIVE), Appointment.appt_date >= today())
    return case((Patient.discharged.is_(True), 'Discharged'), (awaiting, 'Awaiting results'),
                (or_(Patient.review_due.isnot(None), upcoming), 'Under follow-up'), else_='Active')


def next_appt_date_expr():
    return (select(Appointment.appt_date).where(Appointment.patient_id == Patient.id, Appointment.status.in_(ACTIVE), Appointment.appt_date >= today())
            .order_by(Appointment.appt_date).limit(1).scalar_subquery())


def compute(db: Session, patients: list[Patient]) -> dict[str, dict]:
    ids, T = [p.id for p in patients], today()
    out = {p.id: {'last_visit': None, 'next_appt': None, 'status': 'Active', 'follow_up_status': 'No follow-up scheduled', 'attention': None,
                  'attention_kind': None} for p in patients}
    if not ids:
        return out
    last: dict[str, date] = {}
    nxt: dict[str, tuple] = {}
    for aid, pid, d, t, st in db.execute(select(Appointment.id, Appointment.patient_id, Appointment.appt_date, Appointment.appt_time, Appointment.status)
                                         .where(Appointment.patient_id.in_(ids))):
        if st == 'Completed' and (pid not in last or d > last[pid]):
            last[pid] = d
        if st in ACTIVE and d >= T and (pid not in nxt or (d, t or '') < nxt[pid][:2]):
            nxt[pid] = (d, t or '', aid)
    for pid, d in db.execute(select(Consultation.patient_id, Consultation.consult_date).where(Consultation.patient_id.in_(ids), Consultation.consult_date <= T)):
        if d and (pid not in last or d > last[pid]):
            last[pid] = d
    awaiting = set(db.execute(select(DiagnosticTest.patient_id).where(DiagnosticTest.patient_id.in_(ids), DiagnosticTest.status.in_(PENDING_TESTS))).scalars())
    alerts = defaultdict(list)
    for a in db.execute(select(CareGapAlert).where(CareGapAlert.patient_id.in_(ids), CareGapAlert.status.in_(('Open', 'Actioned')))).scalars():
        alerts[a.patient_id].append(a)
    for p in patients:
        o = out[p.id]
        o['last_visit'] = last.get(p.id)
        if p.id in nxt:
            o['next_appt'] = {'date': nxt[p.id][0], 'time': nxt[p.id][1], 'id': nxt[p.id][2]}
        o['status'] = 'Discharged' if p.discharged else 'Awaiting results' if p.id in awaiting else 'Under follow-up' if (p.review_due or p.id in nxt) else 'Active'
        open_ = sorted((a for a in alerts[p.id] if a.status == 'Open'), key=lambda a: (PRI_RANK[a.priority], a.first_seen))
        actioned = [a for a in alerts[p.id] if a.status == 'Actioned']
        if open_:
            o['attention'], o['attention_kind'] = f'{open_[0].category} – {open_[0].reason}', 'gap'
        elif actioned:
            o['attention'], o['attention_kind'] = f'Action in progress – {actioned[0].category}', 'actioned'
        o['follow_up_status'] = ('Discharged – none required' if p.discharged else
                                 'Follow-up overdue' if any(a.rule == 'overdue_followup' and a.status == 'Open' for a in alerts[p.id]) else
                                 'Follow-up scheduled' if p.id in nxt else 'No follow-up scheduled')
    return out
