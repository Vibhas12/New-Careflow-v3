"""Data Import pipeline (SQLAlchemy port of the V2 prototype): validate → preserve original → parse → map → match → check duplicates
→ human review → confirm (each record in its own savepoint).

Safety rules:
  * patient ID is the primary match key; uncertain matches are NEVER merged automatically – they wait for a person
  * duplicates (in the file, in the database, or the whole file re-uploaded) are detected and skipped by default
  * originals and every per-record outcome are kept; nothing is silently dropped
  * for an existing patient blank fields are completed and list items added – existing values are never overwritten
  * priority rows go through the same append-only priority history, under the confirming coordinator's name
"""
import hashlib
import json
import re
from datetime import date
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (Allergy, Appointment, CarePlan, Consultation, Department, Diagnosis, DiagnosticTest, Document, IdSequence, IngestionBatch,
                        IngestionRecord, MedicalHistory, Medication, Patient, PriorityHistory, Referral, Task, TaskEvent, User, UserDepartment)
from app.ingest.parsing import (APPT_STATUS, DEPTS, KIND_FIELDS, PRIORITY_LABEL, PRIORITY_VALUES, IngestError, canonicalise, detect_type, extract_pdf_text,
                                norm_name, parse_csv, parse_date, parse_json, parse_report_text, split_list)
from app.services.common import audit, next_id, today, utcnow

ALLOWED_TYPES = {'csv', 'json', 'pdf'}
D = lambda s: date.fromisoformat(s) if s else None


# ---------------------------------------------------------------- matching helpers
def doctor_lookup(db: Session, ref: str | None) -> str | None:
    if not ref:
        return None
    r = ref.strip().lower()
    return db.execute(select(User.id).where(User.role == 'doctor', User.active.is_(True),
                                            (func.lower(User.id) == r) | (func.lower(User.name) == r) | (func.lower(User.name) == 'dr. ' + r))).scalar()


def find_candidates(db: Session, d: dict) -> list[dict]:
    """Possible existing patients for a record without a usable ID."""
    fn, ln, dob = norm_name(d.get('first_name')), norm_name(d.get('last_name')), parse_date(d.get('dob'))
    if not ln:
        return []
    out = []
    for r in db.execute(select(Patient.id, Patient.first_name, Patient.last_name, Patient.dob)):
        rfn, rln, rdob = norm_name(r.first_name), norm_name(r.last_name), r.dob.isoformat() if r.dob else None
        if rln != ln:
            continue
        c = dict(id=r.id, name=f'{r.first_name} {r.last_name}', dob=rdob)
        if fn and rfn == fn and dob and rdob == dob:
            out.append({**c, 'reason': 'First name, surname and date of birth all match', 'strength': 3})
        elif dob and rdob == dob:
            out.append({**c, 'reason': 'Surname and date of birth match; first name differs', 'strength': 2})
        elif fn and rfn == fn:
            out.append({**c, 'reason': 'Same name; date of birth differs or missing', 'strength': 1})
        elif fn and rfn[:1] == fn[:1] and not dob:
            out.append({**c, 'reason': 'Same surname and first initial', 'strength': 0})
    return sorted(out, key=lambda c: -c['strength'])


def _rec_key(kind: str, pid: str, d: dict):
    return {'consultation': lambda: (pid, d.get('date'), norm_name(d.get('notes'))[:120]),
            'test': lambda: (pid, norm_name(d.get('test_name')), d.get('date')),
            'appointment': lambda: (pid, d.get('date'), d.get('time') or '09:00'),
            'referral': lambda: (pid, norm_name(d.get('referred_to')), norm_name(d.get('reason'))),
            'medication': lambda: (pid, norm_name(d.get('medications'))),
            'allergy': lambda: (pid, norm_name(d.get('allergies'))),
            'history': lambda: (pid, d.get('date'), norm_name(d.get('title'))),
            'task': lambda: (pid, norm_name(d.get('title')), d.get('date')),
            'priority': lambda: (pid, 'priority')}.get(kind, lambda: None)()


def _exists(db: Session, kind: str, pid: str, d: dict) -> bool:
    dt = D(d.get('date')) if d.get('date') and kind != 'medication' else None
    if kind == 'consultation':
        return any(norm_name(n)[:120] == norm_name(d.get('notes'))[:120] for n in db.execute(
            select(Consultation.notes).where(Consultation.patient_id == pid, Consultation.consult_date == dt)).scalars())
    if kind == 'test':
        return any(norm_name(t.name) == norm_name(d.get('test_name')) and dt in (t.result_on, t.completed_on, t.ordered_on)
                   for t in db.execute(select(DiagnosticTest).where(DiagnosticTest.patient_id == pid)).scalars())
    if kind == 'appointment':
        return db.execute(select(Appointment.id).where(Appointment.patient_id == pid, Appointment.appt_date == dt,
                                                       Appointment.appt_time == (d.get('time') or '09:00'))).first() is not None
    if kind == 'referral':
        return any(norm_name(r.referred_to) == norm_name(d.get('referred_to')) and norm_name(r.reason) == norm_name(d.get('reason'))
                   for r in db.execute(select(Referral).where(Referral.patient_id == pid)).scalars())
    if kind == 'medication':
        return norm_name(d.get('medications')) in {norm_name(x) for x in db.execute(select(Medication.description).where(Medication.patient_id == pid)).scalars()}
    if kind == 'allergy':
        return norm_name(d.get('allergies')) in {norm_name(x) for x in db.execute(select(Allergy.substance).where(Allergy.patient_id == pid)).scalars()}
    if kind == 'history':
        return any(norm_name(t) == norm_name(d.get('title')) for t in db.execute(
            select(MedicalHistory.title).where(MedicalHistory.patient_id == pid, MedicalHistory.event_date == dt)).scalars())
    if kind == 'task':
        return any(norm_name(t) == norm_name(d.get('title')) for t in db.execute(select(Task.title).where(Task.patient_id == pid, Task.due == dt)).scalars())
    return False


def validate(db: Session, kind: str, d: dict, creating: bool) -> list[dict]:
    iss = []
    E = lambda m: iss.append({'level': 'error', 'msg': m})
    W = lambda m: iss.append({'level': 'warning', 'msg': m})

    def need_date(key='date', label='date'):
        if not d.get(key):
            E(f'Missing {label}')
        elif not (iso := parse_date(d[key])):
            E(f'Unrecognised {label} "{d[key]}" (use YYYY-MM-DD or DD/MM/YYYY)')
        else:
            d[key] = iso
    if kind == 'patient':
        for f, lab in (('first_name', 'first name'), ('last_name', 'last name')):
            if not d.get(f) and creating:
                E(f'Missing {lab}')
        if d.get('dob'):
            iso = parse_date(d['dob'])
            if not iso:
                E(f'Unrecognised date of birth "{d["dob"]}"')
            elif iso > today().isoformat():
                E('Date of birth is in the future')
            else:
                d['dob'] = iso
        elif creating:
            E('Missing date of birth')
        if d.get('department') and d['department'] not in DEPTS:
            hit = next((x for x in DEPTS if x.lower() == d['department'].lower() or x.lower().startswith(d['department'].lower()[:5])), None)
            if hit:
                d['department'] = hit
            else:
                E(f'Unknown department "{d["department"]}" (expected one of: {", ".join(DEPTS)})')
        elif not d.get('department') and creating:
            E('Missing department')
        if d.get('email') and not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', d['email']):
            W('Email address looks invalid')
    elif kind == 'consultation':
        need_date()
        if not d.get('notes'):
            E('Missing consultation notes')
        if d.get('follow_up'):
            if iso := parse_date(d['follow_up']):
                d['follow_up'] = iso
            else:
                W('Follow-up date not recognised – ignored'); d.pop('follow_up')
    elif kind == 'test':
        need_date()
        if not d.get('test_name'):
            E('Missing test / report type')
        if not d.get('summary') and not d.get('status'):
            W('No result summary – imported as an ordered test')
    elif kind == 'appointment':
        need_date()
        if d.get('status') and d['status'].title() not in APPT_STATUS:
            E(f'Unknown appointment status "{d["status"]}"')
        elif d.get('status'):
            d['status'] = d['status'].title()
        if d.get('time') and not re.fullmatch(r'\d{1,2}:\d{2}', d['time']):
            E(f'Time "{d["time"]}" must look like 14:30')
        elif d.get('time'):
            h, m = d['time'].split(':'); d['time'] = f'{int(h):02d}:{m}'
    elif kind == 'referral':
        if not d.get('referred_to'): E('Missing referral destination')
        if not d.get('reason'): E('Missing referral reason')
        if d.get('date'): need_date()
    elif kind == 'medication':
        if not d.get('medications'): E('Missing medication')
    elif kind == 'allergy':
        if not d.get('allergies'): E('Missing allergy')
    elif kind == 'history':
        need_date()
        if not d.get('title'): E('Missing title')
    elif kind == 'task':
        if not d.get('title'): E('Missing task title')
        if d.get('date'): need_date()
        else: E('Missing due date')
    elif kind == 'priority':
        raw = str(d.get('new_priority') or '').strip()
        if not raw:
            E('Missing priority (High, Medium or Low)')
        elif raw.lower() not in PRIORITY_VALUES:
            E(f'Unknown priority "{raw}" (use High, Medium or Low)')
        else:
            d['new_priority'] = PRIORITY_VALUES[raw.lower()]
        if len(str(d.get('reason') or '').strip()) < 5:
            E('A reason for the priority change is mandatory (at least 5 characters)')
    if kind != 'patient' and d.get('doctor') and not doctor_lookup(db, d['doctor']):
        W(f'Doctor "{d["doctor"]}" not found – the patient\'s assigned doctor will be used')
    return iss


def _patient_has_new_info(db: Session, pid: str, d: dict) -> bool:
    p = db.get(Patient, pid)
    for k in ('email', 'mobile', 'address', 'gender', 'ec_name', 'ec_phone', 'primary_condition', 'secondary_conditions', 'previous_surgeries',
              'family_history', 'ins_provider', 'policy', 'coverage'):
        if d.get(k) and not (getattr(p, k) or '').strip():
            return True
    for k, model, col in (('allergies', Allergy, Allergy.substance), ('medications', Medication, Medication.description), ('diagnoses', Diagnosis, Diagnosis.description)):
        have = {norm_name(x) for x in db.execute(select(col).where(model.patient_id == pid)).scalars()}
        if any(norm_name(x) not in have for x in split_list(d.get(k))):
            return True
    return bool(d.get('care_plan')) and not (p.care_plan and (p.care_plan.plan_text or '').strip())


def evaluate(db: Session, kind: str, d: dict, seen: set | None = None, force_patient: str | None = None, force_new: bool = False,
             batch_new_ids: set | None = None) -> dict:
    """Decide the match status of one canonical record."""
    issues: list[dict] = []
    res = dict(match_status='new', matched_patient_id=None, candidates=[], decision='import')
    pid = d.get('patient_id')
    exists = db.get(Patient, force_patient or pid) if (force_patient or pid) else None
    if force_patient and exists:
        res.update(match_status='matched', matched_patient_id=exists.id)
        issues.append({'level': 'info', 'msg': f'Manually linked to {exists.id} ({exists.first_name} {exists.last_name}) by the reviewer'})
    elif pid and exists:
        ln_ok = not d.get('last_name') or norm_name(d['last_name']) == norm_name(exists.last_name)
        dob_ok = not d.get('dob') or parse_date(d['dob']) == (exists.dob.isoformat() if exists.dob else None)
        if ln_ok and dob_ok:
            res.update(match_status='matched', matched_patient_id=exists.id)
        else:
            res.update(match_status='uncertain', candidates=[dict(id=exists.id, name=f'{exists.first_name} {exists.last_name}',
                                                                  dob=exists.dob.isoformat() if exists.dob else None,
                                                                  reason='ID matches but name/date of birth in the file differ', strength=3)])
            issues.append({'level': 'warning', 'msg': f'Patient ID {pid} belongs to {exists.first_name} {exists.last_name} ({exists.dob}) but the file shows different details – confirm before importing'})
    else:
        cands = [] if (force_new and kind == 'patient') else find_candidates(db, d)
        if pid and not cands and kind != 'patient' and batch_new_ids and pid in batch_new_ids:
            res.update(match_status='matched', matched_patient_id=None, deferred=True)
            issues.append({'level': 'info', 'msg': f'Will attach to patient {pid}, created from the same file'})
        elif cands:
            res.update(match_status='uncertain', candidates=cands)
            issues.append({'level': 'warning', 'msg': (f'Patient ID {pid} was not found. ' if pid else 'No patient ID supplied. ') + 'Possible existing patient(s) found – choose one, or create a new patient'})
        elif kind == 'patient':
            if pid and not re.fullmatch(r'PT-\d{3,6}', pid):
                issues.append({'level': 'warning', 'msg': f'ID "{pid}" is not in PT-#### format – a new ID will be assigned'})
        else:
            res['match_status'] = 'invalid'
            issues.append({'level': 'error', 'msg': (f'Patient ID {pid} not found' if pid else 'No patient ID or identifying details') + ' – record cannot be attached to a patient'})
    issues = validate(db, kind, d, creating=res['match_status'] == 'new') + issues   # validate AFTER matching
    if any(i['level'] == 'error' for i in issues):
        res['match_status'], res['decision'] = 'invalid', 'skip'
    elif res['match_status'] == 'uncertain':
        res['decision'] = 'pending'
    elif res['match_status'] == 'matched':
        target, dup = res['matched_patient_id'] or pid, False
        if res.get('deferred'):
            if kind == 'priority':
                issues.append({'level': 'info', 'msg': f'Priority will be set to {PRIORITY_LABEL[d["new_priority"]]} after the patient is created (default Medium)'})
        elif kind == 'priority':
            cur = db.get(Patient, target).priority
            dup = cur == d['new_priority']
            issues.append({'level': 'info', 'msg': f'Patient is already {PRIORITY_LABEL[cur]} priority – no change' if dup else
                           f'Priority will change: {PRIORITY_LABEL[cur]} → {PRIORITY_LABEL[d["new_priority"]]} (recorded in the priority history when you confirm)'})
        elif kind == 'patient':
            dup = not _patient_has_new_info(db, target, d)
            if dup:
                issues.append({'level': 'info', 'msg': 'Patient already on file – no new information in this record'})
        else:
            dup = _exists(db, kind, target, d)
            if dup:
                issues.append({'level': 'info', 'msg': 'Duplicate – an identical record already exists for this patient'})
        key = _rec_key(kind, target, d)
        if seen is not None and key:
            if key in seen:
                dup = True
                if kind == 'priority':
                    issues = [i for i in issues if not i['msg'].startswith('Priority will change')]
                    issues.append({'level': 'info', 'msg': 'Only one priority change per patient per file – an earlier row already changes this patient'})
                else:
                    issues.append({'level': 'info', 'msg': 'Duplicate of an earlier row in this same file'})
            seen.add(key)
        if dup:
            res['match_status'], res['decision'] = 'duplicate', 'skip'
    elif res['match_status'] == 'new' and seen is not None:
        key = ('newpatient', norm_name(d.get('first_name')), norm_name(d.get('last_name')), d.get('dob'))
        if key in seen:
            res['match_status'], res['decision'] = 'duplicate', 'skip'
            issues.append({'level': 'info', 'msg': 'Duplicate patient – the same person appears earlier in this file'})
        seen.add(key)
    res['issues'] = issues
    return res


# ---------------------------------------------------------------- batch lifecycle
def check_upload(filename: str, data: bytes) -> str | None:
    """Returns a rejection reason, or None if the file may be processed."""
    ft, cfg = detect_type(filename), get_settings()
    if ft not in ALLOWED_TYPES:
        return f'Unsupported file type ".{ft}". Allowed: CSV, JSON, PDF.'
    if not data:
        return 'The file is empty.'
    if len(data) > cfg.max_upload_bytes:
        return f'File is {len(data) / 1048576:.1f} MB – the limit is {cfg.max_upload_bytes / 1048576:.0f} MB.'
    if ft == 'pdf' and not data.startswith(b'%PDF'):
        return 'The file is named .pdf but is not a valid PDF document.'
    if ft in ('csv', 'json') and b'\x00' in data[:2048]:
        return f'The file is named .{ft} but appears to be binary, not text.'
    return None


def _safe_name(n: str) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '_', Path(n).name)[:80] or 'file'


def create_batch(db: Session, user: User, filename: str, data: bytes, label: str = 'Data file uploaded') -> IngestionBatch:
    """Always records the attempt (Rejected / Failed / Needs Review) and preserves the original file."""
    reason = check_upload(filename, data)
    ft, digest, now = detect_type(filename), hashlib.sha256(data).hexdigest() if data else None, utcnow()
    b = IngestionBatch(id=next_id(db, 'ING', 100), filename=Path(filename).name[:255], file_type=ft, size_bytes=len(data), sha256=digest,
                       status='Needs Review', uploaded_by=user.id, uploaded_at=now)
    db.add(b)
    db.flush()
    audit(db, user, label if not reason else 'Data file rejected', entity=b.id, detail=f'{b.filename} ({len(data)} bytes)' + (f': {reason}' if reason else ''))
    if reason:
        b.status, b.message = 'Rejected', reason
        db.commit()
        return b
    up = get_settings().upload_dir
    up.mkdir(parents=True, exist_ok=True)
    stored = up / f'{b.id}__{digest[:10]}__{_safe_name(filename)}'
    stored.write_bytes(data)
    b.stored_path = str(stored)
    text, method, recs, err = None, None, [], None
    try:
        if ft == 'csv':
            recs, method = parse_csv(data), 'csv parser'
        elif ft == 'json':
            recs, method = parse_json(data), 'json parser'
        else:
            text, method = extract_pdf_text(stored)
            d = parse_report_text(text)
            recs = [(1, 'test', d)]
            for k, kind in (('medications', 'medication'), ('allergies', 'allergy')):
                for part in re.split(r'[;,]', d.get(k) or ''):
                    if part.strip() and part.strip().lower() not in ('none', 'nil', 'none recorded'):
                        recs.append((len(recs) + 1, kind, {'patient_id': d.get('patient_id'), 'first_name': d.get('first_name'), 'last_name': d.get('last_name'),
                                                          'dob': d.get('dob'), k: part.strip()}))
    except IngestError as e:
        err = str(e)
    except Exception as e:                     # corrupt file or parser bug → recorded, never silent
        err = f'Could not read the file: {e}'
    db.add(Document(id=next_id(db, 'DOC', 100), batch_id=b.id, filename=b.filename, file_type=ft, size_bytes=len(data), sha256=digest, stored_path=str(stored),
                    doc_type={'pdf': 'Medical report (PDF)', 'csv': 'Data file (CSV)', 'json': 'Data file (JSON)'}.get(ft), extracted_text=text,
                    extraction_method=method, uploaded_by=user.id, uploaded_at=now))
    b.extraction_method = method
    if err:
        b.status, b.message = 'Failed', err
        db.commit()
        return b
    dup_of = db.execute(select(IngestionBatch.id).where(IngestionBatch.sha256 == digest, IngestionBatch.id != b.id,
                                                        IngestionBatch.status.in_(('Imported', 'Partially Imported'))).order_by(IngestionBatch.uploaded_at)).scalar()
    seen, new_ids = set(), set()
    for rn, kind, raw in sorted(recs, key=lambda t: (t[1] != 'patient', t[0])):
        if kind == 'unknown':
            db.add(IngestionRecord(batch_id=b.id, row_no=rn, kind='unknown', raw=raw, mapped={}, match_status='invalid',
                                   issues=[{'level': 'error', 'msg': 'Unrecognised record type'}], decision='skip', result='failed', result_message='Unrecognised record type'))
            continue
        d = canonicalise(kind, raw) if ft != 'pdf' else dict(raw)
        ev = evaluate(db, kind, d, seen, batch_new_ids=new_ids)
        if kind == 'patient' and ev['match_status'] == 'new' and d.get('patient_id') and re.fullmatch(r'PT-\d{3,6}', d['patient_id']):
            new_ids.add(d['patient_id'])
        if dup_of:
            ev['issues'].append({'level': 'info', 'msg': f'This exact file was already imported in batch {dup_of}'})
            ev['match_status'], ev['decision'] = 'duplicate', 'skip'
        invalid = ev['match_status'] == 'invalid'
        db.add(IngestionRecord(batch_id=b.id, row_no=rn, kind=kind, raw=json.loads(json.dumps(raw, default=str)), mapped=d, match_status=ev['match_status'],
                               matched_patient_id=ev['matched_patient_id'], candidates=ev['candidates'], issues=ev['issues'], decision=ev['decision'],
                               result='failed' if invalid else None,
                               result_message='; '.join(i['msg'] for i in ev['issues'] if i['level'] == 'error') if invalid else None))
    b.n_records = len(recs)
    b.message = f'Parsed {len(recs)} record(s) from {b.filename}.' + (f' Warning: this exact file was already imported in {dup_of} – all records are marked duplicate.' if dup_of else '')
    db.commit()
    return b


def review_record(db: Session, user: User, rec: IngestionRecord, *, fields: dict | None, patient_id: str | None, decision: str | None) -> None:
    """Reviewer edits fields, links an uncertain record to a patient / creates a new one, or toggles import/skip."""
    b = db.get(IngestionBatch, rec.batch_id)
    if b.status != 'Needs Review':
        raise IngestError('This batch has already been finalised')
    if rec.kind == 'unknown':
        raise IngestError('This record type is not recognised and cannot be edited')
    d = dict(rec.mapped or {})
    for k, v in (fields or {}).items():
        if k in KIND_FIELDS.get(rec.kind, []):
            if v in (None, ''):
                d.pop(k, None)
            else:
                d[k] = str(v).strip()
    force_patient, force_new = None, False
    if patient_id == 'NEW':
        if rec.kind != 'patient':
            raise IngestError('Only patient records can be created as new patients')
        force_new = True
    elif patient_id:
        if db.get(Patient, patient_id) is None:
            raise IngestError('Chosen patient does not exist')
        force_patient = patient_id
    elif rec.matched_patient_id:
        force_patient = rec.matched_patient_id
    ev = evaluate(db, rec.kind, d, None, force_patient=force_patient, force_new=force_new)
    dec = decision if decision in ('import', 'skip') else ev['decision']
    if ev['match_status'] in ('invalid', 'duplicate') and decision != 'import':
        dec = 'skip'
    if ev['match_status'] == 'invalid':
        dec = 'skip'
    if ev['match_status'] == 'uncertain' and dec == 'import':
        raise IngestError('Choose which patient this record belongs to (or create a new patient) before importing it')
    invalid = ev['match_status'] == 'invalid'
    rec.mapped, rec.match_status, rec.matched_patient_id, rec.candidates, rec.issues, rec.decision = d, ev['match_status'], ev['matched_patient_id'], ev['candidates'], ev['issues'], dec
    rec.result = 'failed' if invalid else None
    rec.result_message = '; '.join(i['msg'] for i in ev['issues'] if i['level'] == 'error') if invalid else None
    audit(db, user, 'Import record reviewed', patient_id=ev['matched_patient_id'], entity=rec.batch_id, detail=f'row {rec.row_no}: decision={dec}, match={ev["match_status"]}')
    db.commit()


def _new_patient_id(db: Session, wanted: str | None) -> str:
    if wanted and re.fullmatch(r'PT-\d{3,6}', wanted) and db.get(Patient, wanted) is None:
        n = int(wanted.split('-')[1])
        seq = db.get(IdSequence, 'PT')
        if seq is None:
            db.add(IdSequence(prefix='PT', value=n))
        elif seq.value < n:
            seq.value = n
        return wanted
    while True:
        pid = next_id(db, 'PT', 1000)
        if db.get(Patient, pid) is None:
            return pid


def _link_lists(db: Session, p: Patient, d: dict, bid: str):
    have = {'a': {norm_name(x.substance) for x in p.allergies}, 'm': {norm_name(x.description) for x in p.medications}, 'd': {norm_name(x.description) for x in p.diagnoses}}
    for s in split_list(d.get('allergies')):
        if norm_name(s) not in have['a']:
            p.allergies.append(Allergy(substance=s, source_batch_id=bid)); have['a'].add(norm_name(s))
    for s in split_list(d.get('medications')):
        if norm_name(s) not in have['m']:
            p.medications.append(Medication(description=s, source_batch_id=bid)); have['m'].add(norm_name(s))
    for s in split_list(d.get('diagnoses')):
        if norm_name(s) not in have['d']:
            p.diagnoses.append(Diagnosis(description=s, source_batch_id=bid)); have['d'].add(norm_name(s))


def _hist(db: Session, pid: str, dt: date, typ: str, title: str, detail: str, bid: str) -> str:
    hid = 'HI-' + next_id(db, 'HIS', 100).split('-')[1]
    db.add(MedicalHistory(id=hid, patient_id=pid, event_date=dt, type=typ, title=title, detail=detail, source_batch_id=bid))
    return hid


def save_record(db: Session, user: User, b: IngestionBatch, rec: IngestionRecord) -> tuple[str, str]:
    """Persist one reviewed record. Returns (entity id, message). Raises on failure (the caller records it)."""
    kind, d, bid, fname, now, T = rec.kind, dict(rec.mapped), b.id, b.filename, utcnow(), today()
    if kind == 'patient' and not rec.matched_patient_id:
        if not db.get(Department, d['department']):
            db.add(Department(name=d['department']))
        pid = _new_patient_id(db, d.get('patient_id'))
        doc = doctor_lookup(db, d.get('doctor')) or db.execute(
            select(User.id).where(User.role == 'doctor', User.active.is_(True), User.departments.any(UserDepartment.department == d['department']))
            .order_by(User.id)).scalars().first()
        p = Patient(id=pid, first_name=d['first_name'], last_name=d['last_name'], dob=D(d['dob']), gender=d.get('gender') or 'Not recorded', email=d.get('email'),
                    mobile=d.get('mobile'), address=d.get('address'), ec_name=d.get('ec_name'), ec_phone=d.get('ec_phone'), department=d['department'],
                    primary_condition=d.get('primary_condition') or 'Not recorded', secondary_conditions=d.get('secondary_conditions'),
                    previous_surgeries=d.get('previous_surgeries') or 'None', family_history=d.get('family_history') or 'None recorded',
                    ins_provider=d.get('ins_provider'), policy=d.get('policy'), coverage=d.get('coverage'), doctor_id=doc,
                    coord_id=user.id if user.role == 'coordinator' else None, registered_on=T, priority='med', priority_updated_at=now, source_batch_id=bid)
        db.add(p)
        db.flush()
        db.add(PriorityHistory(patient_id=pid, previous_priority=None, new_priority='med', comment=f'Default priority assigned when the patient was imported (batch {bid})',
                               user_id=user.id, user_name=user.name, user_role=user.role, changed_at=now))
        _link_lists(db, p, d, bid)
        if d.get('care_plan'):
            p.care_plan = CarePlan(plan_text=d['care_plan'], start_date=T, source_batch_id=bid)
        _hist(db, pid, T, 'Registration', 'Patient record imported', f'Created from {fname} ({bid}).', bid)
        audit(db, user, 'Patient imported (new)', patient_id=pid, entity=bid, detail=f'{p.first_name} {p.last_name} from {fname}')
        return pid, f'Created patient {pid}'
    pid = rec.matched_patient_id or d.get('patient_id')
    p = db.get(Patient, pid)
    if kind == 'patient':
        n = 0
        for k in ('email', 'mobile', 'address', 'gender', 'ec_name', 'ec_phone', 'primary_condition', 'secondary_conditions', 'previous_surgeries',
                  'family_history', 'ins_provider', 'policy', 'coverage'):
            if d.get(k) and not (getattr(p, k) or '').strip():
                setattr(p, k, d[k]); n += 1
        _link_lists(db, p, d, bid)
        if d.get('care_plan'):
            if p.care_plan is None:
                p.care_plan = CarePlan(plan_text=d['care_plan'], start_date=T, source_batch_id=bid)
            elif not (p.care_plan.plan_text or '').strip():
                p.care_plan.plan_text, p.care_plan.source_batch_id = d['care_plan'], bid
        _hist(db, pid, T, 'Update', 'Patient information updated from import', f'Blank fields completed and new list items added from {fname} ({bid}). Existing values were not overwritten.', bid)
        audit(db, user, 'Patient updated by import', patient_id=pid, entity=bid, detail=f'{n} blank field(s) completed from {fname}')
        return pid, f'Updated {pid}'
    doc = doctor_lookup(db, d.get('doctor')) or p.doctor_id
    if kind == 'consultation':
        eid = next_id(db, 'CON', 4000)
        db.add(Consultation(id=eid, patient_id=pid, doctor_id=doc, consult_date=D(d['date']), notes=d['notes'], diagnosis=d.get('diagnosis'),
                            prescription=d.get('prescription'), plan=d.get('plan'), follow_up=D(d.get('follow_up')), created_on=now, source_batch_id=bid))
        fu = D(d.get('follow_up'))
        if fu and (p.review_due is None or p.review_due < fu):
            p.review_due = fu
    elif kind == 'test':
        eid, has = next_id(db, 'TST', 3000), bool(d.get('summary'))
        status = d.get('status') if d.get('status') in ('Ordered', 'Scheduled', 'Completed', 'Result Available', 'Reviewed') else ('Result Available' if has else 'Ordered')
        doc_row = db.execute(select(Document).where(Document.batch_id == bid)).scalar() if b.file_type == 'pdf' else None
        dt = D(d['date'])
        db.add(DiagnosticTest(id=eid, patient_id=pid, name=d['test_name'], ordered_by=doc, ordered_on=dt, status=status, completed_on=dt if has else None,
                              result_on=dt if has else None, abnormal=str(d.get('abnormal', '')).lower() in ('1', 'true', 'yes', 'y'), priority='Routine',
                              notes=f'Imported from {fname}', result_summary=d.get('summary') if has else None,
                              result_source=f'Imported report – {fname} ({bid}); extracted automatically, awaiting clinician review' if has else None,
                              document_id=doc_row.id if doc_row else None, source_batch_id=bid))
        if doc_row:
            doc_row.patient_id, doc_row.doc_type = pid, 'Diagnostic report'
    elif kind == 'appointment':
        eid = next_id(db, 'APT', 5000)
        db.add(Appointment(id=eid, patient_id=pid, doctor_id=doc, dept=p.department, appt_date=D(d['date']), appt_time=d.get('time') or '09:00',
                           type=d.get('type') or 'Consultation', status=d.get('status') or 'Scheduled', created_on=now, booked_by=user.id,
                           notes=d.get('notes'), source_batch_id=bid))
    elif kind == 'referral':
        eid = next_id(db, 'REF', 2000)
        st = d['status'].title() if d.get('status') and d['status'].title() in ('Pending', 'Booked', 'Completed') else 'Pending'
        db.add(Referral(id=eid, patient_id=pid, referred_to=d['referred_to'], reason=d['reason'], status=st, created_on=D(d.get('date')) or T,
                        referred_by=doc, source_batch_id=bid))
    elif kind == 'medication':
        _link_lists(db, p, {'medications': d['medications']}, bid); eid = f'{pid}/medication'
    elif kind == 'allergy':
        _link_lists(db, p, {'allergies': d['allergies']}, bid); eid = f'{pid}/allergy'
    elif kind == 'history':
        eid = _hist(db, pid, D(d['date']), d.get('type') or 'Imported', d['title'], d.get('detail') or '', bid)
    elif kind == 'task':
        eid = next_id(db, 'TSK', 7000)
        db.add(Task(id=eid, title=d['title'], patient_id=pid, priority=d.get('priority') if d.get('priority') in ('high', 'med', 'low') else 'med',
                    assignee=p.coord_id or doc, created=T, due=D(d['date']), status='New', kind='followup', source='Imported file',
                    description=d.get('notes'), source_batch_id=bid,
                    events=[TaskEvent(seq=0, ts=now, by_name=user.name, text=f'Task imported from {fname} ({bid})')]))
    elif kind == 'priority':
        old, new = p.priority, d['new_priority']
        if old == new:
            return f'{pid}/priority', f'No change – already {PRIORITY_LABEL[new]}'
        comment = f'{d["reason"].strip()} (imported from {fname}, batch {bid})'
        p.priority, p.priority_updated_at = new, now
        h = PriorityHistory(patient_id=pid, previous_priority=old, new_priority=new, comment=comment, user_id=user.id, user_name=user.name,
                            user_role=user.role, changed_at=now)
        db.add(h)
        db.flush()
        audit(db, user, 'Patient priority changed', patient_id=pid, entity=f'PRI-{h.id}', detail=f'{PRIORITY_LABEL[old]} → {PRIORITY_LABEL[new]}: {comment}')
        return f'PRI-{h.id}', f'Priority changed {PRIORITY_LABEL[old]} → {PRIORITY_LABEL[new]}'
    else:
        raise IngestError(f'Unsupported record type {kind}')
    audit(db, user, f'Imported {kind}', patient_id=pid, entity=bid, detail=f'{eid} from {fname}')
    return eid, f'Saved {kind} {eid}'


def confirm_batch(db: Session, user: User, bid: str) -> tuple[dict, set[str]]:
    """Import every record marked 'import'. Each record is its own savepoint; failures are recorded, never dropped.
    Returns (result summary, IDs of patients touched – for the care-gap rescan)."""
    b = db.execute(select(IngestionBatch).where(IngestionBatch.id == bid).with_for_update()).scalar_one_or_none()
    if b is None:
        raise IngestError('Batch not found')
    if b.status != 'Needs Review':
        raise IngestError(f'Batch is {b.status} – only batches awaiting review can be confirmed')
    recs = list(db.execute(select(IngestionRecord).where(IngestionRecord.batch_id == bid).order_by(IngestionRecord.kind != 'patient', IngestionRecord.id)).scalars())
    pend = [r for r in recs if r.decision == 'pending']
    if pend:
        raise IngestError(f'{len(pend)} record(s) need a manual patient-match decision before import (rows: ' + ', '.join(str(r.row_no) for r in pend[:8]) + ')')
    ok = skipped = failed = 0
    touched: set[str] = set()
    for r in recs:
        if r.result == 'failed' and r.match_status == 'invalid':
            failed += 1; continue
        if r.decision != 'import':
            r.result, r.result_message = 'skipped', f'Skipped ({r.match_status})'; skipped += 1; continue
        sp = db.begin_nested()
        try:
            eid, msg = save_record(db, user, b, r)
            db.flush()
            sp.commit()
            r.result, r.result_message, r.saved_entity = 'saved', msg, eid
            touched.add(eid if r.kind == 'patient' else (r.matched_patient_id or (r.mapped or {}).get('patient_id')))
            ok += 1
        except Exception as e:
            sp.rollback()
            r.result, r.result_message = 'failed', str(e)[:500]; failed += 1
    b.status = 'Partially Imported' if failed else 'Imported'
    b.confirmed_by, b.confirmed_at, b.n_imported, b.n_skipped, b.n_failed = user.id, utcnow(), ok, skipped, failed
    b.message = f'{ok} imported, {skipped} skipped, {failed} failed/invalid.'
    audit(db, user, 'Data import confirmed', entity=bid, detail=f'{b.filename}: {ok} imported, {skipped} skipped, {failed} failed')
    db.commit()
    return {'status': b.status, 'imported': ok, 'skipped': skipped, 'failed': failed}, {t for t in touched if t}


def cancel_batch(db: Session, user: User, bid: str) -> IngestionBatch:
    b = db.get(IngestionBatch, bid)
    if b is None:
        raise IngestError('Batch not found')
    if b.status != 'Needs Review':
        raise IngestError('Only batches awaiting review can be cancelled')
    b.status, b.message = 'Cancelled', 'Cancelled by reviewer – nothing was imported'
    for r in db.execute(select(IngestionRecord).where(IngestionRecord.batch_id == bid, IngestionRecord.result.is_(None))).scalars():
        r.result, r.result_message = 'skipped', 'Batch cancelled'
    audit(db, user, 'Data import cancelled', entity=bid, detail='')
    db.commit()
    return b
