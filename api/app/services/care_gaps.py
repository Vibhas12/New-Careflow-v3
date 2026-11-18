"""Care-gap detection (deterministic, explainable, configurable) and the alert lifecycle.

Rules are a direct port of the V2 engine. Thresholds and per-rule priorities come from app settings ('rules').
Lifecycle:  Open ──approve──▶ Actioned (task created)        Open ──dismiss (reason)──▶ Dismissed
            Open/Actioned ──rule no longer fires──▶ Resolved (automatic)   Resolved ──fires again──▶ Open
Detection and suggestions never change a patient's priority; they only feed the advisory "suggested priority".
"""
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppSetting, Appointment, CareGapAlert, DiagnosticTest, Patient, Prescription, Referral, Task, User
from app.services import tasks as task_svc
from app.services.access import get_visible_patient
from app.services.common import audit, fail, today, utcnow, fmt_d

RULES = {
    'missed_appt': ('Missed Appointments', 'Missed appointment with no later appointment',
                    'An appointment is marked Missed and the patient has no later scheduled, confirmed or completed appointment.'),
    'overdue_followup': ('Overdue Follow-ups', 'Review date passed without consultation',
                         'The recorded review date has passed (plus grace days), no completed appointment exists on/after it and none is scheduled.'),
    'pending_test': ('Pending Diagnostic Tests', 'Test not scheduled or not completed',
                     'A test is Ordered but unscheduled for N days, or Scheduled with a date that has passed without completion.'),
    'referral': ('Outstanding Referrals', 'Referral pending beyond threshold', 'A referral is still Pending after N days.'),
    'results_review': ('Results Awaiting Doctor Review', 'Result available but not reviewed',
                       'A result is available and no doctor review is recorded. Priority depends on whether values fall outside the reference range.'),
    'med_adherence': ('Potential Medication Adherence Concerns', 'Prescription refill overdue or due soon',
                      'The recorded refill date has passed with no renewal, or falls inside the renewal window. This is a prompt for review, not a clinical judgement.'),
    'incomplete': ('Incomplete Care Activities', 'Overdue task or unconfirmed upcoming appointment',
                   'A task is past its due date, or an appointment within N days is still unconfirmed.'),
}
DEFAULT_RULES = {'followupGraceDays': 0, 'testPendingDays': 3, 'referralDays': 7, 'medRefillWindowDays': 7, 'taskGraceDays': 0, 'confirmWindowDays': 3,
                 'enabled': {k: True for k in RULES},
                 'priorities': {'missed_appt': 'high', 'overdue_followup': 'high', 'pending_test': 'med', 'referral': 'high',
                                'results_abnormal': 'high', 'results_normal': 'med', 'med_adherence': 'med', 'incomplete': 'med'}}
PRI_RANK = {'high': 0, 'med': 1, 'low': 2}
ACTIVE_LIKE = ('Scheduled', 'Confirmed', 'Completed')


def rule_settings(db: Session) -> dict:
    s = db.get(AppSetting, 'settings')
    r = {**DEFAULT_RULES, **((s.value if s else {}).get('rules') or {})}
    r['enabled'] = {**DEFAULT_RULES['enabled'], **(r.get('enabled') or {})}
    r['priorities'] = {**DEFAULT_RULES['priorities'], **(r.get('priorities') or {})}
    return r


def _d(x: date | None) -> str:
    return f'{fmt_d(x)}' if x else '—'


def detect(db: Session, patient_ids: list[str] | None = None) -> list[dict]:
    """Returns the gaps that fire right now (pure read; no writes)."""
    R, T = rule_settings(db), today()
    en, pr = R['enabled'], R['priorities']
    pq = select(Patient).where(Patient.draft.is_(False), Patient.discharged.is_(False))
    if patient_ids is not None:
        pq = pq.where(Patient.id.in_(patient_ids))
    patients = list(db.execute(pq).scalars())
    ids = [p.id for p in patients]
    if not ids:
        return []

    def by_patient(model):
        out = defaultdict(list)
        for x in db.execute(select(model).where(model.patient_id.in_(ids))).scalars():
            out[x.patient_id].append(x)
        return out
    appts, tests, refs, rxs, tasks = (by_patient(m) for m in (Appointment, DiagnosticTest, Referral, Prescription, Task))
    gaps = []

    def add(rule, p, entity, priority, reason, evidence, title, text, kind, due, assignee=None):
        cat, name, _ = RULES[rule]
        gaps.append(dict(id=f'ALR-{rule}-{entity}', rule=rule, category=cat, rule_name=name, patient_id=p.id, entity=str(entity), priority=priority,
                         reason=reason, evidence=evidence, action={'title': title, 'text': text, 'kind': kind, 'due': due.isoformat()},
                         assignee=assignee or p.coord_id))

    for p in patients:
        pa = appts[p.id]
        later = lambda d0: any(a.appt_date > d0 and a.status in ACTIVE_LIKE for a in pa)
        ev_a = lambda a: {'ref': a.id, 'text': f'Appointment {_d(a.appt_date)} {a.appt_time or ""} ({a.type}) – status {a.status}'}
        if en['missed_appt']:
            for a in pa:
                if a.status == 'Missed' and not later(a.appt_date):
                    add('missed_appt', p, a.id, pr['missed_appt'], f'The appointment on {_d(a.appt_date)} was missed and no later appointment is recorded.',
                        [ev_a(a), {'ref': p.id, 'text': f'No scheduled, confirmed or completed appointment after {_d(a.appt_date)}'}],
                        'Contact patient and rebook missed appointment', 'Contact the patient and rebook the missed appointment.', 'contact', T + timedelta(days=1))
        if en['overdue_followup'] and p.review_due and p.review_due < T - timedelta(days=R['followupGraceDays']):
            done = any(a.status == 'Completed' and a.appt_date >= p.review_due for a in pa)
            fut = any(a.status in ('Scheduled', 'Confirmed') and a.appt_date >= T for a in pa)
            if not done and not fut:
                add('overdue_followup', p, f'{p.id}-{p.review_due.isoformat()}', pr['overdue_followup'],
                    f"The patient's scheduled review date ({_d(p.review_due)}, {(T - p.review_due).days} days ago) has passed and no completed consultation or future appointment is recorded.",
                    [{'ref': p.id, 'text': f'Review due {_d(p.review_due)}'}],
                    'Contact patient and arrange follow-up appointment', 'Contact the patient and arrange a follow-up appointment.', 'followup', T + timedelta(days=1))
        if en['pending_test']:
            for t in tests[p.id]:
                ev = [{'ref': t.id, 'text': f'{t.name} – status {t.status}, ordered {_d(t.ordered_on)}' + (f', scheduled {_d(t.scheduled_date)}' if t.scheduled_date else '')}]
                if t.status == 'Ordered' and t.ordered_on and (T - t.ordered_on).days >= R['testPendingDays']:
                    add('pending_test', p, t.id, pr['pending_test'], f'{t.name} was ordered {(T - t.ordered_on).days} days ago and has not been scheduled.', ev,
                        f'Schedule {t.name} with patient', f'Contact the patient to schedule the {t.name}.', 'test', T + timedelta(days=1))
                if t.status == 'Scheduled' and t.scheduled_date and t.scheduled_date < T:
                    add('pending_test', p, t.id, pr['pending_test'], f'{t.name} was scheduled for {_d(t.scheduled_date)} but no completion is recorded.', ev,
                        f'Confirm whether {t.name} was completed', f'Check with the patient/provider whether the {t.name} took place and rebook if not.', 'test', T + timedelta(days=1))
        if en['results_review']:
            for t in tests[p.id]:
                if t.status == 'Result Available':
                    add('results_review', p, t.id, pr['results_abnormal'] if t.abnormal else pr['results_normal'],
                        f'{t.name} result available since {_d(t.result_on)}' + ('; one or more values fall outside the reference range.' if t.abnormal else '.') + ' No doctor review recorded.',
                        [{'ref': t.id, 'text': f'{t.name} result – ' + ('values outside reference range flagged' if t.abnormal else 'within reference range')}],
                        f'Review {t.name} result', f'Doctor to review the {t.name} result.', 'review', T, assignee=p.doctor_id)
        if en['referral']:
            for r in refs[p.id]:
                if r.status == 'Pending' and r.created_on and (T - r.created_on).days >= R['referralDays']:
                    add('referral', p, r.id, pr['referral'], f'Referral to {r.referred_to} has been pending for {(T - r.created_on).days} days (threshold {R["referralDays"]}).',
                        [{'ref': r.id, 'text': f'Referral to {r.referred_to} created {_d(r.created_on)} – Pending'}],
                        f'Chase referral: {r.referred_to}', 'Contact the receiving service and confirm a booking date for the referral.', 'referral', T + timedelta(days=2))
        if en['med_adherence']:
            for x in rxs[p.id]:
                if x.status != 'Active' or not x.refill_due:
                    continue
                dd = (x.refill_due - T).days
                ev = [{'ref': x.id, 'text': f'{x.drug} – refill due {_d(x.refill_due)}' + (', no renewal recorded' if dd < 0 else '')}]
                if dd < 0:
                    add('med_adherence', p, x.id, pr['med_adherence'], f'Refill for "{x.drug}" was due {_d(x.refill_due)} and no renewal is recorded – possible adherence concern.', ev,
                        'Check prescription renewal with patient', 'Contact the patient about the overdue prescription refill and ask the doctor to review renewal.', 'medication', T + timedelta(days=1))
                elif dd <= R['medRefillWindowDays']:
                    add('med_adherence', p, x.id, pr['med_adherence'], f'Prescription renewal for "{x.drug}" falls due on {_d(x.refill_due)} (within {R["medRefillWindowDays"]} days).', ev,
                        'Prepare prescription renewal review', 'Flag the upcoming renewal to the doctor for review.', 'medication', max(T, x.refill_due - timedelta(days=2)))
        if en['incomplete']:
            for k in tasks[p.id]:
                if k.status != 'Completed' and k.due and k.due < T - timedelta(days=R['taskGraceDays']):
                    add('incomplete', p, k.id, pr['incomplete'], f'Task "{k.title}" was due {_d(k.due)} and is still {k.status}.', [{'ref': k.id, 'text': f'Task due {_d(k.due)} – {k.status}'}],
                        f'Complete or reassign overdue task: {k.title}', 'Complete or reassign the overdue task.', 'admin', T, assignee=k.assignee)
            for a in pa:
                if a.status == 'Scheduled' and a.appt_date >= T and (a.appt_date - T).days <= R['confirmWindowDays']:
                    add('incomplete', p, a.id, pr['incomplete'], f'Appointment on {_d(a.appt_date)} {a.appt_time} is within {R["confirmWindowDays"]} days and the patient has not confirmed.',
                        [ev_a(a)], 'Call patient to confirm appointment', 'Call the patient to confirm the upcoming appointment.', 'contact', max(T, a.appt_date - timedelta(days=1)))
    return sorted(gaps, key=lambda g: PRI_RANK[g['priority']])


def rescan(db: Session, patient_ids: list[str] | None = None, *, commit: bool = True) -> dict:
    """Synchronise stored alerts with what the rules detect now. patient_ids=None → everyone."""
    ids = [i for i in (patient_ids or []) if i] if patient_ids is not None else None
    if ids == []:
        return {'opened': 0, 'reopened': 0, 'resolved': 0, 'open': 0}
    found = {g['id']: g for g in detect(db, ids)}
    q = select(CareGapAlert)
    if ids is not None:
        q = q.where(CareGapAlert.patient_id.in_(ids))
    existing = {a.id: a for a in db.execute(q).scalars()}
    now, opened, reopened, resolved = utcnow(), 0, 0, 0
    for gid, g in found.items():
        a = existing.get(gid)
        if a is None:
            db.add(CareGapAlert(**g, status='Open', first_seen=now, last_seen=now)); opened += 1
            continue
        for k in ('priority', 'reason', 'evidence', 'action', 'category', 'rule_name'):
            setattr(a, k, g[k])
        if a.status not in ('Actioned',):          # keep the assignee chosen when the alert was actioned
            a.assignee = g['assignee']
        a.last_seen = now
        if a.status == 'Resolved':
            a.status, a.resolved_at = 'Open', None; reopened += 1
    for aid, a in existing.items():
        if aid not in found and a.status in ('Open', 'Actioned'):
            a.status, a.resolved_at = 'Resolved', now; resolved += 1
            audit(db, None, 'Care gap resolved automatically', patient_id=a.patient_id, entity=a.id, detail=f'Rule no longer fires – {a.reason}')
    if commit:
        db.commit()                                  # no LLM call here: AI wording is generated only on request
    still_open = sum(1 for gid in found if gid not in existing or existing[gid].status == 'Open')
    return {'opened': opened, 'reopened': reopened, 'resolved': resolved, 'open': still_open}


def suggested_priorities(db: Session, patient_ids: list[str]) -> dict[str, str]:
    """Advisory only: High if any open alert is high, Medium if any is medium, else Low."""
    out = {pid: 'low' for pid in patient_ids}
    if not patient_ids:
        return out
    for pid, pri in db.execute(select(CareGapAlert.patient_id, CareGapAlert.priority).where(CareGapAlert.patient_id.in_(patient_ids), CareGapAlert.status == 'Open')):
        if PRI_RANK[pri] < PRI_RANK[out[pid]]:
            out[pid] = pri
    return out


# ---------------------------------------------------------------- human decisions
def _alert_for(db: Session, user: User, alert_id: str) -> CareGapAlert:
    if user.role not in ('coordinator', 'doctor'):
        fail(403, 'Only care coordinators and doctors can act on alerts')
    a = db.get(CareGapAlert, alert_id)
    if a is None:
        fail(404, 'Alert not found')
    get_visible_patient(db, user, a.patient_id)
    return a


def approve(db: Session, user: User, alert_id: str, *, title: str | None = None, text: str | None = None, assignee: str | None = None,
            due: date | None = None, priority: str | None = None) -> CareGapAlert:
    """Turn the suggested action into a real task (optionally modified). One open task per alert."""
    a = _alert_for(db, user, alert_id)
    if a.status != 'Open':
        fail(409, f'The alert is {a.status.lower()}')
    p = db.get(Patient, a.patient_id)
    act = a.action
    modified = any(v is not None for v in (title, text, assignee, due, priority))
    from app.services.recommendation_agent import is_current
    ai = is_current(a)                                  # current LLM wording, if any, replaces the rule template's wording
    base_title, base_text = (a.ai_task_title, a.ai_text) if ai else (act['title'], act['text'])
    wording = f' Wording by {a.ai_model} (AI suggestion).' if ai and not (title or text) else ''
    k = task_svc.create(db, user, title=title or f"{base_title} – {p.first_name} {p.last_name}", patient_id=p.id, priority=priority or a.priority,
                        assignee=assignee or a.assignee or p.coord_id, due=due or date.fromisoformat(act['due']), kind=act['kind'],
                        source='Care-gap alert (approved)', description=f"{text or base_text} Rule: {a.rule_name}. Approved by {user.name}.{wording}", commit=False)
    k.alert_id = a.id
    a.status, a.task_id, a.assignee, a.actioned_by, a.actioned_at = 'Actioned', k.id, k.assignee, user.id, utcnow()
    audit(db, user, 'Recommendation modified and approved' if modified else 'Recommendation approved', patient_id=p.id, entity=a.id,
          detail=f'{a.category} → task {k.id}')
    db.commit()
    return a


def dismiss(db: Session, user: User, alert_id: str, reason: str) -> CareGapAlert:
    a = _alert_for(db, user, alert_id)
    if a.status != 'Open':
        fail(409, f'The alert is {a.status.lower()}')
    if len((reason or '').strip()) < 5:
        fail(422, 'A reason is required to dismiss an alert (at least 5 characters)')
    a.status, a.dismissed_by, a.dismiss_reason = 'Dismissed', user.id, reason.strip()
    audit(db, user, 'Alert dismissed', patient_id=a.patient_id, entity=a.id, detail=f'{a.category} – {a.dismiss_reason}')
    db.commit()
    return a
