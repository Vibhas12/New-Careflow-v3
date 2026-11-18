"""Seed data (fictional). Source: backend/seed/seed_data.json.

    seed_reference()  staff accounts, departments, settings – runs automatically on an empty database. NO patients.
    seed_clinical()   the 15 V2 demo patients – only when the 'V2 demo' scenario is chosen on the sign-in screen (app/demo_data.py).

    python -m app.seed            (run `alembic upgrade head` first) – accounts and settings only

Dates in the seed file are shifted so the scenarios stay relative to today (same behaviour as the V2 prototype).
"""
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.catalog import DEPARTMENTS
from app.core.config import get_settings
from app.core.security import hash_password
from app.db import SessionLocal
from app.models import (AppSetting, Allergy, Appointment, AuditLog, CarePlan, Consultation, Department, Diagnosis,
                        DiagnosticTest, IdSequence, MedicalHistory, Medication, Notification, Patient, Prescription,
                        Referral, Reminder, Task, TaskEvent, TestResultValue, User, UserDepartment)
from app.services import priority as priority_svc

DATE_RE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})(.*)$')
NONE_WORDS = {'', 'none', 'none recorded', 'n/a', 'nil', 'not recorded'}


def _shift(o, days):
    if isinstance(o, str):
        m = DATE_RE.match(o)
        if m and days:
            return (date(int(m[1]), int(m[2]), int(m[3])) + timedelta(days=days)).isoformat() + m[4]
        return o
    if isinstance(o, list):
        return [_shift(x, days) for x in o]
    if isinstance(o, dict):
        return {k: _shift(v, days) for k, v in o.items()}
    return o


def D(s):
    return date.fromisoformat(s[:10]) if s else None


def DT(s):
    if not s:
        return None
    if len(s) == 10:
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(s.replace('Z', '+00:00'))


def split_list(s):
    return [p.strip() for p in str(s or '').split(';') if p.strip() and p.strip().lower() not in NONE_WORDS]


def is_seeded(db: Session) -> bool:
    return db.get(AppSetting, 'seeded_on') is not None


def _load_raw() -> dict:
    raw = json.loads(get_settings().seed_file.read_text(encoding='utf-8'))
    return _shift(raw, (date.today() - date.fromisoformat(raw['seededOn'])).days)


def seed_reference(db: Session) -> bool:
    """Staff accounts, departments and configuration only – NO patient data. Runs once, on an empty database."""
    if db.execute(select(User.id).limit(1)).first():
        return False
    S, cfg = _load_raw(), get_settings()
    pw = hash_password(cfg.seed_demo_password)
    depts = set(S['settings'].get('depts', {})) | {d for u in S['users'] for d in u.get('depts') or []} | set(DEPARTMENTS)
    db.add_all(Department(name=n, enabled=S['settings'].get('depts', {}).get(n, True)) for n in sorted(depts))
    db.flush()
    for u in S['users']:
        db.add(User(id=u['id'], name=u['name'], role=u['role'], title=u.get('title'), email=u['email'].lower(), phone=u.get('phone'),
                    active=u.get('active', True), password_hash=pw, must_change_password=False,
                    departments=[UserDepartment(department=d) for d in u.get('depts') or []]))
    db.add(AppSetting(key='settings', value=S['settings']))
    db.commit()
    return True


def seed(db: Session) -> bool:
    """Reference data + the V2 demo patients (used by the test-suite and the 'V2 demo' scenario)."""
    created = seed_reference(db)
    seed_clinical(db)
    return created


def seed_clinical(db: Session) -> None:
    """The 15 fictional V2 demo patients and all their records. Expects an empty clinical database."""
    S = _load_raw()
    for p in S['patients']:
        pat = Patient(id=p['id'], first_name=p['first'], last_name=p['last'], dob=D(p.get('dob')), gender=p.get('gender'), email=p.get('email'),
                      mobile=p.get('mobile'), address=p.get('address'), ec_name=p.get('ecName'), ec_phone=p.get('ecPhone'), department=p.get('department'),
                      primary_condition=p.get('primary'), secondary_conditions=p.get('secondary'), previous_surgeries=p.get('prevSurg'),
                      family_history=p.get('famHist'), ins_provider=p.get('insProvider'), policy=p.get('policy'), coverage=p.get('coverage'),
                      doctor_id=p.get('doctorId'), coord_id=p.get('coordId'), registered_on=D(p.get('registeredOn')), review_due=D(p.get('reviewDue')),
                      plan_review_due=D(p.get('planReviewDue')), discharged=bool(p.get('discharged')), draft=bool(p.get('draft')), priority=p.get('priority') or 'med',
                      priority_updated_at=datetime.now(timezone.utc))
        pat.allergies = [Allergy(substance=s) for s in dict.fromkeys(split_list(p.get('allergies')))]
        pat.medications = [Medication(description=s) for s in dict.fromkeys(split_list(p.get('meds')))]
        pat.diagnoses = [Diagnosis(description=s) for s in dict.fromkeys(split_list(p.get('prevDx')))]
        if p.get('treatmentPlan') or p.get('treatmentStart'):
            pat.care_plan = CarePlan(plan_text=p.get('treatmentPlan'), start_date=D(p.get('treatmentStart')))
        db.add(pat)
        db.flush()
        priority_svc.record_initial(db, pat, 'System (seed)', 'system', 'Initial priority assigned when synthetic demo data was loaded')

    for a in S['appointments']:
        db.add(Appointment(id=a['id'], patient_id=a['patientId'], doctor_id=a.get('doctorId'), dept=a.get('dept'), appt_date=D(a['date']),
                           appt_time=a.get('time'), type=a.get('type'), status=a['status'], created_on=DT(a.get('createdOn')), notes=a.get('notes')))
    for t in S['tests']:
        r = t.get('result') or {}
        db.add(DiagnosticTest(id=t['id'], patient_id=t['patientId'], name=t['name'], ordered_by=t.get('orderedBy'), ordered_on=D(t.get('orderedOn')),
                              scheduled_date=D(t.get('scheduledDate')), status=t['status'], completed_on=D(t.get('completedOn')),
                              result_on=D(t.get('resultOn')), reviewed_on=D(t.get('reviewedOn')), reviewed_by=t.get('reviewedBy'),
                              review_note=t.get('reviewNote'), abnormal=bool(t.get('abnormal')), priority=t.get('priority'), notes=t.get('notes'),
                              result_summary=r.get('summary'), result_source=r.get('source'),
                              values=[TestResultValue(seq=i, analyte=v.get('k'), value=None if v.get('v') is None else str(v['v']), unit=v.get('u'),
                                                      ref_range=v.get('ref'), flag=v.get('flag') or None) for i, v in enumerate(r.get('values') or [])]))
    for r in S['referrals']:
        db.add(Referral(id=r['id'], patient_id=r['patientId'], referred_to=r.get('to'), reason=r.get('reason'), status=r['status'],
                        created_on=D(r.get('createdOn')), referred_by=r.get('by')))
    for x in S['prescriptions']:
        db.add(Prescription(id=x['id'], patient_id=x['patientId'], drug=x.get('drug'), prescribed_by=x.get('prescribedBy'), rx_date=D(x.get('date')),
                            refill_due=D(x.get('refillDue')), status=x.get('status')))
    for c in S['consultations']:
        db.add(Consultation(id=c['id'], patient_id=c['patientId'], doctor_id=c.get('doctorId'), consult_date=D(c.get('date')), notes=c.get('notes'),
                            diagnosis=c.get('diagnosis'), prescription=c.get('prescription'), plan=c.get('plan'), follow_up=D(c.get('followUp')),
                            instructions=c.get('instructions'), created_on=DT(c.get('createdOn'))))
    for k in S['tasks']:
        db.add(Task(id=k['id'], title=k['title'], patient_id=k.get('patientId'), priority=k.get('priority'), assignee=k.get('assignee'),
                    created=D(k.get('created')), due=D(k.get('due')), status=k['status'], kind=k.get('kind'), source=k.get('source'),
                    description=k.get('desc'), completed_on=D(k.get('completedOn')), alert_id=k.get('alertId'),
                    events=[TaskEvent(seq=i, ts=DT(h.get('ts')), by_name=h.get('by'), text=h.get('text')) for i, h in enumerate(k.get('history') or [])]))
    for r in S['reminders']:
        db.add(Reminder(id=r['id'], kind=r.get('kind'), ref_id=r.get('refId'), patient_id=r.get('patientId'), offset_label=r.get('offset'),
                        channel=r.get('channel'), scheduled_for=DT(r.get('scheduledFor')), status=r.get('status'), sent_at=DT(r.get('sentAt')),
                        label=r.get('label'), message=r.get('message'), simulated=r.get('simulated', True)))
    for n in S['notifications']:
        db.add(Notification(id=n['id'], ts=DT(n.get('ts')), to_user=n.get('toUser'), to_role=n.get('toRole'), title=n.get('title'), text=n.get('text'),
                            route=n.get('route'), patient_id=n.get('patientId'), is_read=bool(n.get('read')), level=n.get('level')))
    # the seed file's communications log, patient feedback and clinical outcomes are not loaded (features removed)
    for h in S['history']:
        db.add(MedicalHistory(id=h['id'], patient_id=h['patientId'], event_date=D(h.get('date')), type=h.get('type'), title=h.get('title'), detail=h.get('detail')))
    for a in reversed(S['audit']):                       # seed file is newest-first
        db.add(AuditLog(ts=DT(a['ts']), user_id=a.get('userId'), user_name=a.get('user'), role=a.get('role'), action=a['action'],
                        patient_id=a.get('patientId'), entity=a.get('entity'), detail=a.get('detail')))
    for prefix, val in (S.get('seq') or {}).items():
        seq = db.get(IdSequence, prefix)
        if seq is None:
            db.add(IdSequence(prefix=prefix, value=int(val)))
        else:
            seq.value = max(seq.value, int(val))
    db.commit()
    from app.services import care_gaps            # first detection run, so alerts exist before the scheduler's first tick
    care_gaps.rescan(db, None)


def main():
    """python -m app.seed  → accounts + settings only (no patients). Demo data is chosen on the sign-in screen."""
    with SessionLocal() as db:
        print('Created staff accounts and settings (no patient data).' if seed_reference(db) else 'Accounts already exist – nothing changed.')


if __name__ == '__main__':
    sys.exit(main())
