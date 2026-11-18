"""Method B: file-based ingestion (CSV / JSON / PDF) – parse, map, match, validate, review, import.

Safety rules implemented here:
  * patient IDs are the primary matching reference; uncertain matches are NEVER auto-merged (they wait for a human decision)
  * duplicate patients / records / documents are detected and skipped by default
  * original files and per-record outcomes are preserved; nothing is silently discarded
  * extraction (incl. OCR) is rule-based – extracted text is shown for review before anything is saved
"""
import csv, hashlib, io, json, os, re, shutil, subprocess, tempfile
from datetime import date, datetime
from pathlib import Path

from . import config, db

DEPTS = ['Cardiology', 'Neurology', 'Oncology', 'Orthopedics', 'General Medicine', 'Mental Health']
APPT_STATUS = ['Scheduled', 'Confirmed', 'Completed', 'Missed', 'Cancelled']
TEST_NAMES = ['Blood Test', 'HbA1c', 'Lipid Profile', 'Thyroid Function', 'ECG', 'X-Ray', 'MRI', 'EEG']

KIND_ALIASES = {
    'patient': 'patient', 'patients': 'patient', 'demographics': 'patient',
    'consultation': 'consultation', 'consultations': 'consultation', 'note': 'consultation', 'notes': 'consultation', 'consultation_note': 'consultation',
    'test': 'test', 'tests': 'test', 'report': 'test', 'reports': 'test', 'diagnostic': 'test', 'diagnostics': 'test', 'diagnostic_report': 'test', 'diagnostic_reports': 'test',
    'appointment': 'appointment', 'appointments': 'appointment',
    'referral': 'referral', 'referrals': 'referral',
    'medication': 'medication', 'medications': 'medication',
    'allergy': 'allergy', 'allergies': 'allergy',
    'history': 'history', 'medical_history': 'history', 'event': 'history', 'events': 'history',
    'task': 'task', 'tasks': 'task', 'outstanding_task': 'task', 'outstanding_tasks': 'task',
    'priority': 'priority', 'priorities': 'priority', 'priority_change': 'priority', 'priority_changes': 'priority', 'patient_priority': 'priority',
}
# accepted spellings for a patient priority in a file → stored value
PRIORITY_VALUES = {'high': 'high', 'h': 'high', 'medium': 'med', 'med': 'med', 'm': 'med', 'moderate': 'med', 'low': 'low', 'l': 'low'}
PRIORITY_LABEL = {'high': 'High', 'med': 'Medium', 'low': 'Low'}
FIELD_ALIASES = {
    'patient_id': ['patient_id', 'patientid', 'patient_ref', 'mrn', 'id', 'pid'],
    'first_name': ['first_name', 'firstname', 'first', 'given_name', 'forename'],
    'last_name': ['last_name', 'lastname', 'last', 'surname', 'family_name'],
    'name': ['name', 'patient_name', 'full_name'],
    'dob': ['dob', 'date_of_birth', 'birth_date', 'birthdate'],
    'gender': ['gender', 'sex'], 'email': ['email', 'email_address'], 'mobile': ['mobile', 'phone', 'mobile_number', 'telephone'],
    'address': ['address'], 'ec_name': ['emergency_contact_name', 'ec_name', 'emergency_contact'], 'ec_phone': ['emergency_contact_number', 'ec_phone', 'emergency_phone'],
    'department': ['department', 'dept', 'speciality', 'specialty'],
    'primary_condition': ['primary_condition', 'primary_illness', 'condition', 'primary_diagnosis'],
    'secondary_conditions': ['secondary_conditions', 'secondary_condition', 'comorbidities'],
    'allergies': ['allergies', 'allergy', 'substance'], 'medications': ['medications', 'medication', 'existing_medications', 'drug', 'description'],
    'diagnoses': ['previous_diagnoses', 'diagnoses', 'prior_diagnoses'], 'previous_surgeries': ['previous_surgeries', 'surgeries'],
    'family_history': ['family_history'], 'doctor': ['doctor_id', 'doctor', 'assigned_doctor', 'consultant', 'clinician'],
    'care_plan': ['care_plan', 'treatment_plan'], 'ins_provider': ['insurance_provider', 'ins_provider'], 'policy': ['policy', 'policy_number'],
    'coverage': ['coverage', 'coverage_type'],
    'date': ['date', 'consultation_date', 'appointment_date', 'report_date', 'event_date', 'due', 'due_date', 'start_date'],
    'time': ['time', 'appointment_time'], 'type': ['type', 'appointment_type', 'event_type'], 'status': ['status'],
    'notes': ['notes', 'clinical_notes', 'note', 'consultation_notes'], 'diagnosis': ['diagnosis'], 'prescription': ['prescription'],
    'plan': ['plan', 'treatment_plan'], 'follow_up': ['follow_up', 'followup', 'follow_up_date', 'review_date'],
    'test_name': ['test_name', 'test', 'report_type', 'investigation'], 'summary': ['result_summary', 'summary', 'findings', 'result', 'impression'],
    'abnormal': ['abnormal'], 'referred_to': ['referred_to', 'referral_to', 'to', 'service'], 'reason': ['reason', 'referral_reason', 'priority_reason', 'comment'],
    'title': ['title', 'task', 'task_title'], 'detail': ['detail', 'details', 'description_long'], 'priority': ['task_priority'],
    'new_priority': ['priority', 'new_priority', 'patient_priority'],
}
CANON = {a: k for k, al in FIELD_ALIASES.items() for a in al}
KIND_FIELDS = {
    'patient': ['patient_id', 'first_name', 'last_name', 'dob', 'gender', 'email', 'mobile', 'address', 'ec_name', 'ec_phone', 'department', 'primary_condition',
                'secondary_conditions', 'allergies', 'medications', 'diagnoses', 'previous_surgeries', 'family_history', 'doctor', 'care_plan', 'ins_provider', 'policy', 'coverage'],
    'consultation': ['patient_id', 'first_name', 'last_name', 'dob', 'date', 'doctor', 'notes', 'diagnosis', 'prescription', 'plan', 'follow_up'],
    'test': ['patient_id', 'first_name', 'last_name', 'dob', 'test_name', 'date', 'summary', 'status', 'abnormal', 'doctor'],
    'appointment': ['patient_id', 'first_name', 'last_name', 'dob', 'date', 'time', 'type', 'status', 'doctor', 'notes'],
    'referral': ['patient_id', 'first_name', 'last_name', 'dob', 'referred_to', 'reason', 'status', 'date', 'doctor'],
    'medication': ['patient_id', 'first_name', 'last_name', 'dob', 'medications'],
    'allergy': ['patient_id', 'first_name', 'last_name', 'dob', 'allergies'],
    'history': ['patient_id', 'first_name', 'last_name', 'dob', 'date', 'type', 'title', 'detail'],
    'task': ['patient_id', 'first_name', 'last_name', 'dob', 'title', 'date', 'priority', 'notes'],
    'priority': ['patient_id', 'first_name', 'last_name', 'dob', 'new_priority', 'reason'],
}
# patient-reference fields must not be re-mapped by alias collisions (e.g. 'id' ⇒ patient_id only in patient/other kinds)


def norm_key(k):
    return re.sub(r'[^a-z0-9]+', '_', str(k).strip().lower()).strip('_')


def norm_name(s):
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


MONTHS = {m: i + 1 for i, m in enumerate(['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'])}


def parse_date(s):
    """ISO, dd/mm/yyyy (UK order), dd-mm-yyyy, '5 Mar 2024'. Returns ISO string or None."""
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    try:
        m = re.fullmatch(r'(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ].*)?', s)
        if m:
            return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
        m = re.fullmatch(r'(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})', s)
        if m:
            return date(int(m[3]), int(m[2]), int(m[1])).isoformat()
        m = re.fullmatch(r'(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?,?\s+(\d{4})', s)
        if m and m[2].lower() in MONTHS:
            return date(int(m[3]), MONTHS[m[2].lower()], int(m[1])).isoformat()
    except ValueError:
        return None
    return None


# ------------------------------------------------------------------ parsing
class IngestError(Exception):
    pass


def detect_type(filename):
    ext = Path(filename).suffix.lower().lstrip('.')
    return ext


def parse_csv(data):
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise IngestError('CSV is not valid UTF-8 text')
    rd = csv.DictReader(io.StringIO(text))
    if not rd.fieldnames:
        raise IngestError('CSV has no header row')
    rows = []
    for i, r in enumerate(rd, start=2):
        if not any((v or '').strip() for v in r.values() if isinstance(v, str)):
            continue
        rows.append((i, {norm_key(k): (v or '').strip() for k, v in r.items() if k}))
        if len(rows) > 2000:
            raise IngestError('CSV has more than 2000 rows – split the file')
    if not rows:
        raise IngestError('CSV contains no data rows')
    out = []
    for rn, r in rows:
        kind = KIND_ALIASES.get(norm_key(r.get('record_type') or r.get('kind') or 'patient'))
        if not kind:
            out.append((rn, 'unknown', r)); continue
        out.append((rn, kind, r))
    return out


def parse_json(data):
    try:
        obj = json.loads(data.decode('utf-8-sig'))
    except Exception as e:
        raise IngestError('JSON could not be parsed: ' + str(e))
    out, n = [], 0
    def add(kind, rec):
        nonlocal n
        n += 1
        if not isinstance(rec, dict):
            out.append((n, 'unknown', {'value': rec})); return
        out.append((n, kind, {norm_key(k): v for k, v in rec.items()}))
    if isinstance(obj, dict):
        hit = False
        for k, v in obj.items():
            kk = KIND_ALIASES.get(norm_key(k))
            if kk and isinstance(v, list):
                hit = True
                for rec in v:
                    add(kk, rec)
        if not hit:
            add(KIND_ALIASES.get(norm_key(obj.get('record_type', 'patient')), 'unknown'), obj)
    elif isinstance(obj, list):
        for rec in obj:
            kd = KIND_ALIASES.get(norm_key((rec or {}).get('record_type', (rec or {}).get('type', 'patient')))) if isinstance(rec, dict) else None
            add(kd or ('patient' if isinstance(rec, dict) and 'record_type' not in rec else 'unknown'), rec)
    else:
        raise IngestError('JSON must be an object or an array of records')
    if not out:
        raise IngestError('JSON contains no records')
    return out


def _run(cmd, timeout=60):
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def extract_pdf_text(path):
    """1) pdftotext  2) pypdf  3) OCR (pdftoppm + tesseract) for scanned PDFs. Returns (text, method)."""
    text, method = '', ''
    try:
        r = _run(['pdftotext', '-layout', str(path), '-'])
        text, method = r.stdout.decode('utf-8', 'replace'), 'pdftotext'
    except Exception:
        pass
    if len(text.strip()) < 25:
        try:
            from pypdf import PdfReader
            text = '\n'.join((p.extract_text() or '') for p in PdfReader(str(path)).pages); method = 'pypdf'
        except Exception:
            pass
    if len(text.strip()) < 25:                      # likely a scan → OCR
        try:
            with tempfile.TemporaryDirectory() as td:
                _run(['pdftoppm', '-r', '200', '-png', str(path), os.path.join(td, 'p')], 120)
                parts = []
                for img in sorted(Path(td).glob('p*.png'))[:10]:
                    r = _run(['tesseract', str(img), '-', '--psm', '6'], 120)
                    parts.append(r.stdout.decode('utf-8', 'replace'))
                if ''.join(parts).strip():
                    text, method = '\n'.join(parts), 'ocr (tesseract)'
        except Exception:
            pass
    if not text.strip():
        raise IngestError('No text could be extracted from the PDF (text extraction and OCR both returned nothing)')
    return text, method


HEAD = re.compile(r'^\s*([A-Za-z][A-Za-z /&]{1,32}?)\s*[:\-]\s*(.*)$')
SECTION_STOP = {'patient', 'patient name', 'name', 'dob', 'date of birth', 'patient id', 'report date', 'date', 'report type', 'test', 'investigation',
                'medications', 'medication', 'allergies', 'reported by', 'consultant', 'clinician', 'requested by', 'findings', 'impression', 'result', 'results',
                'conclusion', 'summary', 'gender', 'sex', 'department', 'nhs number'}


def parse_report_text(text):
    """Rule-based extraction of a diagnostic report. Returns a canonical mapped dict (no clinical interpretation)."""
    lines = [l.rstrip() for l in text.replace('\r', '').split('\n')]
    kv = {}
    for i, l in enumerate(lines):
        m = HEAD.match(l)
        if m:
            key = m[1].strip().lower()
            if key not in kv:
                kv[key] = (m[2].strip(), i)
    def first(*keys):
        for k in keys:
            if k in kv and kv[k][0]:
                return kv[k][0]
        return None
    def section(*keys):
        for k in keys:
            if k in kv:
                v, i = kv[k]
                buf = [v] if v else []
                for l in lines[i + 1:]:
                    if not l.strip():
                        if buf:
                            break
                        continue
                    m = HEAD.match(l)
                    if m and m[1].strip().lower() in SECTION_STOP:
                        break
                    buf.append(l.strip())
                return ' '.join(buf).strip()[:1500] or None
        return None
    out = {}
    m = re.search(r'\b(PT-\d{3,6})\b', text)
    out['patient_id'] = (first('patient id', 'patient ref', 'mrn') or (m[1] if m else None))
    if out['patient_id']:
        mm = re.search(r'PT-\d{3,6}', out['patient_id'], re.I)
        out['patient_id'] = mm[0].upper() if mm else None
    nm = first('patient name', 'patient', 'name')
    if nm:
        nm = re.sub(r'\(.*?\)|PT-\d+', '', nm).strip()
        nm = re.sub(r'^(mr|mrs|ms|miss|dr)\.?\s+', '', nm, flags=re.I)
        parts = nm.split()
        if len(parts) >= 2:
            out['first_name'], out['last_name'] = parts[0], parts[-1]
    out['dob'] = first('dob', 'date of birth')
    out['date'] = first('report date', 'date of report', 'date reported', 'date', 'collected', 'date collected')
    out['test_name'] = first('report type', 'test', 'investigation', 'examination', 'procedure')
    out['summary'] = section('findings', 'impression', 'result', 'results', 'conclusion', 'summary')
    out['doctor'] = first('reported by', 'consultant', 'clinician', 'requested by')
    meds, alg = first('medications', 'medication'), first('allergies')
    if meds:
        out['medications'] = meds
    if alg:
        out['allergies'] = alg
    return {k: v for k, v in out.items() if v}


# ------------------------------------------------------------------ mapping & matching
def canonicalise(kind, raw):
    """raw keys → canonical keys using aliases; keep only fields relevant to the kind."""
    out = {}
    wanted = set(KIND_FIELDS.get(kind, []))
    for k, v in raw.items():
        c = CANON.get(norm_key(k))
        if kind == 'patient' and c == 'date':
            continue
        if kind == 'consultation' and k == 'plan':
            c = 'plan'
        if c in wanted and v not in (None, ''):
            if isinstance(v, list):
                v = '; '.join(str(x) for x in v)
            elif isinstance(v, (dict, bool)):
                v = v if isinstance(v, bool) else json.dumps(v)
            out[c] = v if isinstance(v, bool) else str(v).strip()
    if 'name' in raw and 'first_name' not in out and kind in KIND_FIELDS:
        parts = str(raw['name']).split()
        if len(parts) >= 2:
            out['first_name'], out['last_name'] = parts[0], parts[-1]
    if 'patient_id' in out:
        out['patient_id'] = out['patient_id'].strip().upper()
    return out


def doctor_lookup(conn, ref):
    if not ref:
        return None
    r = conn.execute("SELECT id FROM users WHERE role='doctor' AND active=1 AND (lower(id)=lower(?) OR lower(name)=lower(?) OR lower(name)=lower('Dr. '||?))", (ref, ref, ref)).fetchone()
    return r['id'] if r else None


def find_candidates(conn, d):
    """Candidate existing patients for a record without a usable ID. Returns list of {id,name,dob,reason,strength}."""
    fn, ln, dob = norm_name(d.get('first_name')), norm_name(d.get('last_name')), parse_date(d.get('dob'))
    out = []
    if not ln:
        return out
    for r in conn.execute("SELECT id, first_name, last_name, dob FROM patients"):
        rfn, rln = norm_name(r['first_name']), norm_name(r['last_name'])
        if rln != ln:
            continue
        if fn and rfn == fn and dob and r['dob'] == dob:
            out.append(dict(id=r['id'], name=f"{r['first_name']} {r['last_name']}", dob=r['dob'], reason='First name, surname and date of birth all match', strength=3))
        elif dob and r['dob'] == dob:
            out.append(dict(id=r['id'], name=f"{r['first_name']} {r['last_name']}", dob=r['dob'], reason='Surname and date of birth match; first name differs', strength=2))
        elif fn and rfn == fn:
            out.append(dict(id=r['id'], name=f"{r['first_name']} {r['last_name']}", dob=r['dob'], reason='Same name; date of birth differs or missing', strength=1))
        elif fn and rfn[:1] == fn[:1] and not dob:
            out.append(dict(id=r['id'], name=f"{r['first_name']} {r['last_name']}", dob=r['dob'], reason='Same surname and first initial', strength=0))
    return sorted(out, key=lambda c: -c['strength'])


def _rec_key(kind, pid, d):
    if kind == 'consultation':
        return (pid, d.get('date'), norm_name(d.get('notes'))[:120])
    if kind == 'test':
        return (pid, norm_name(d.get('test_name')), d.get('date'))
    if kind == 'appointment':
        return (pid, d.get('date'), d.get('time') or '09:00')
    if kind == 'referral':
        return (pid, norm_name(d.get('referred_to')), norm_name(d.get('reason')))
    if kind == 'medication':
        return (pid, norm_name(d.get('medications')))
    if kind == 'allergy':
        return (pid, norm_name(d.get('allergies')))
    if kind == 'history':
        return (pid, d.get('date'), norm_name(d.get('title')))
    if kind == 'task':
        return (pid, norm_name(d.get('title')), d.get('date'))
    if kind == 'priority':
        return (pid, 'priority')          # one priority change per patient per file
    return None


def _exists(conn, kind, pid, d):
    if kind == 'consultation':
        for r in conn.execute("SELECT notes FROM consultations WHERE patient_id=? AND consult_date=?", (pid, d.get('date'))):
            if norm_name(r['notes'])[:120] == norm_name(d.get('notes'))[:120]:
                return True
    elif kind == 'test':
        for r in conn.execute("SELECT name FROM diagnostic_tests WHERE patient_id=? AND coalesce(result_on,completed_on,ordered_on)=?", (pid, d.get('date'))):
            if norm_name(r['name']) == norm_name(d.get('test_name')):
                return True
    elif kind == 'appointment':
        return conn.execute("SELECT 1 FROM appointments WHERE patient_id=? AND appt_date=? AND appt_time=?", (pid, d.get('date'), d.get('time') or '09:00')).fetchone() is not None
    elif kind == 'referral':
        for r in conn.execute("SELECT referred_to, reason FROM referrals WHERE patient_id=?", (pid,)):
            if norm_name(r['referred_to']) == norm_name(d.get('referred_to')) and norm_name(r['reason']) == norm_name(d.get('reason')):
                return True
    elif kind == 'medication':
        for r in conn.execute("SELECT description FROM medications WHERE patient_id=?", (pid,)):
            if norm_name(r['description']) == norm_name(d.get('medications')):
                return True
    elif kind == 'allergy':
        for r in conn.execute("SELECT substance FROM allergies WHERE patient_id=?", (pid,)):
            if norm_name(r['substance']) == norm_name(d.get('allergies')):
                return True
    elif kind == 'history':
        for r in conn.execute("SELECT title FROM medical_history WHERE patient_id=? AND event_date=?", (pid, d.get('date'))):
            if norm_name(r['title']) == norm_name(d.get('title')):
                return True
    elif kind == 'task':
        for r in conn.execute("SELECT title FROM tasks WHERE patient_id=? AND due=?", (pid, d.get('date'))):
            if norm_name(r['title']) == norm_name(d.get('title')):
                return True
    return False


def validate(conn, kind, d, creating=True):
    """Returns list of issues (level error|warning|info)."""
    iss = []
    E = lambda m: iss.append({'level': 'error', 'msg': m})
    W = lambda m: iss.append({'level': 'warning', 'msg': m})
    def need_date(key='date', label='date'):
        if not d.get(key):
            E(f'Missing {label}')
        else:
            iso = parse_date(d[key])
            if not iso:
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
            elif iso > date.today().isoformat():
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
            iso = parse_date(d['follow_up'])
            if iso: d['follow_up'] = iso
            else: W('Follow-up date not recognised – ignored'); d.pop('follow_up')
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
    elif kind == 'referral':
        if not d.get('referred_to'): E('Missing referral destination')
        if not d.get('reason'): E('Missing referral reason')
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
    if kind != 'patient' and d.get('doctor') and not doctor_lookup(conn, d['doctor']):
        W(f'Doctor "{d["doctor"]}" not found – the patient\'s assigned doctor will be used')
    return iss


def evaluate(conn, kind, d, seen_keys=None, force_patient=None, force_new=False, batch_new_ids=None):
    """Decide match status for one canonical record. Returns dict for ingestion_records."""
    issues = []
    res = dict(match_status='new', matched_patient_id=None, candidates=[], decision='import')
    pid = d.get('patient_id')
    exists = conn.execute("SELECT id, first_name, last_name, dob FROM patients WHERE id=?", (force_patient or pid,)).fetchone() if (force_patient or pid) else None
    if force_patient and exists:
        res.update(match_status='matched', matched_patient_id=exists['id'])
        issues.append({'level': 'info', 'msg': f'Manually linked to {exists["id"]} ({exists["first_name"]} {exists["last_name"]}) by the reviewer'})
    elif pid and exists:
        ln_ok = (not d.get('last_name')) or norm_name(d['last_name']) == norm_name(exists['last_name'])
        dob_ok = (not d.get('dob')) or d['dob'] == exists['dob']
        if ln_ok and dob_ok:
            res.update(match_status='matched', matched_patient_id=exists['id'])
        else:
            res.update(match_status='uncertain', candidates=[dict(id=exists['id'], name=f"{exists['first_name']} {exists['last_name']}", dob=exists['dob'],
                                                                   reason='ID matches but name/date of birth in the file differ', strength=3)])
            issues.append({'level': 'warning', 'msg': f'Patient ID {pid} belongs to {exists["first_name"]} {exists["last_name"]} ({exists["dob"]}) but the file shows different details – confirm before importing'})
    else:
        cands = [] if (force_new and kind == 'patient') else find_candidates(conn, d)
        if pid and not cands and kind != 'patient' and batch_new_ids and pid in batch_new_ids:
            res.update(match_status='matched', matched_patient_id=None, deferred=True)
            issues.append({'level': 'info', 'msg': f'Will attach to patient {pid}, created from the same file'})
        elif cands:
            res.update(match_status='uncertain', candidates=cands)
            issues.append({'level': 'warning', 'msg': ('Patient ID ' + pid + ' was not found. ' if pid else 'No patient ID supplied. ') + 'Possible existing patient(s) found – choose one, or create a new patient'})
        elif kind == 'patient':
            if pid and not re.fullmatch(r'PT-\d{3,6}', pid):
                issues.append({'level': 'warning', 'msg': f'ID "{pid}" is not in PT-#### format – a new ID will be assigned'})
            res.update(match_status='new')
        else:
            res.update(match_status='invalid')
            issues.append({'level': 'error', 'msg': ('Patient ID ' + pid + ' not found' if pid else 'No patient ID or identifying details') + ' – record cannot be attached to a patient'})
    # validate AFTER matching: a patient matched by ID needs no demographics, a new patient does
    issues = validate(conn, kind, d, creating=(res['match_status'] == 'new')) + issues
    # decide
    if any(i['level'] == 'error' for i in issues):
        if res['match_status'] != 'invalid':
            res['_was'] = res['match_status']
        res['match_status'] = 'invalid'
        res['decision'] = 'skip'
    elif res['match_status'] == 'uncertain':
        res['decision'] = 'pending'
    elif res['match_status'] == 'matched':
        target = res['matched_patient_id'] or pid
        dup = False
        if res.get('deferred'):
            if kind == 'priority':
                issues.append({'level': 'info', 'msg': f'Priority will be set to {PRIORITY_LABEL[d["new_priority"]]} after the patient is created (default Medium)'})
        elif kind == 'priority':
            cur = conn.execute("SELECT priority FROM patients WHERE id=?", (target,)).fetchone()['priority']
            dup = cur == d['new_priority']
            issues.append({'level': 'info', 'msg': f'Patient is already {PRIORITY_LABEL[cur]} priority – no change' if dup else
                           f'Priority will change: {PRIORITY_LABEL[cur]} → {PRIORITY_LABEL[d["new_priority"]]} (recorded in the priority history when you confirm)'})
        elif kind == 'patient':
            dup = not _patient_has_new_info(conn, target, d)
            if dup:
                issues.append({'level': 'info', 'msg': 'Patient already on file – no new information in this record'})
        else:
            dup = _exists(conn, kind, target, d)
            if dup:
                issues.append({'level': 'info', 'msg': 'Duplicate – an identical record already exists for this patient'})
        key = _rec_key(kind, target, d)
        if seen_keys is not None and key:
            if key in seen_keys:
                dup = True
                if kind == 'priority':
                    issues = [i for i in issues if not i['msg'].startswith('Priority will change')]
                    issues.append({'level': 'info', 'msg': 'Only one priority change per patient per file – an earlier row already changes this patient'})
                else:
                    issues.append({'level': 'info', 'msg': 'Duplicate of an earlier row in this same file'})
            seen_keys.add(key)
        if dup:
            res['match_status'], res['decision'] = 'duplicate', 'skip'
    elif res['match_status'] == 'new':
        if seen_keys is not None:
            key = ('newpatient', norm_name(d.get('first_name')), norm_name(d.get('last_name')), d.get('dob'))
            if key in seen_keys:
                res['match_status'], res['decision'] = 'duplicate', 'skip'
                issues.append({'level': 'info', 'msg': 'Duplicate patient – the same person appears earlier in this file'})
            seen_keys.add(key)
    res['issues'] = issues
    return res


def _patient_has_new_info(conn, pid, d):
    p = conn.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
    cols = {'email': 'email', 'mobile': 'mobile', 'address': 'address', 'gender': 'gender', 'ec_name': 'ec_name', 'ec_phone': 'ec_phone',
            'primary_condition': 'primary_condition', 'secondary_conditions': 'secondary_conditions', 'previous_surgeries': 'previous_surgeries',
            'family_history': 'family_history', 'ins_provider': 'ins_provider', 'policy': 'policy', 'coverage': 'coverage'}
    for k, c in cols.items():
        if d.get(k) and not (p[c] or '').strip():
            return True
    from .mapping import split_list
    for k, table, col in (('allergies', 'allergies', 'substance'), ('medications', 'medications', 'description'), ('diagnoses', 'diagnoses', 'description')):
        have = {norm_name(r[0]) for r in conn.execute(f"SELECT {col} FROM {table} WHERE patient_id=?", (pid,))}
        if any(norm_name(x) not in have for x in split_list(d.get(k))):
            return True
    if d.get('care_plan'):
        r = conn.execute("SELECT plan_text FROM care_plans WHERE patient_id=?", (pid,)).fetchone()
        if not r or not (r[0] or '').strip():
            return True
    return False


# ------------------------------------------------------------------ batch lifecycle
def sha256(b):
    return hashlib.sha256(b).hexdigest()


def safe_name(n):
    return re.sub(r'[^A-Za-z0-9._-]+', '_', os.path.basename(n))[:80] or 'file'


def create_batch(conn, user, filename, data, file_type=None, reject_reason=None):
    """Validate + persist the original + parse into reviewable records. Always writes an ingestion_history row."""
    bid = db.next_id(conn, 'ING', 100)
    ft = file_type or detect_type(filename)
    digest = sha256(data) if data else None
    now = db.now_iso()
    conn.execute("INSERT INTO ingestion_batches(id,filename,file_type,size_bytes,sha256,status,message,uploaded_by,uploaded_by_name,uploaded_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                 (bid, filename, ft, len(data or b''), digest, 'Needs Review', None, user['id'], user['name'], now))
    if reject_reason:
        conn.execute("UPDATE ingestion_batches SET status='Rejected', message=? WHERE id=?", (reject_reason, bid))
        return bid
    # preserve original
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored = config.UPLOAD_DIR / f"{bid}__{digest[:10]}__{safe_name(filename)}"
    stored.write_bytes(data)
    conn.execute("UPDATE ingestion_batches SET stored_path=? WHERE id=?", (str(stored), bid))
    doc_id = db.next_id(conn, 'DOC', 100)
    text, method, recs, err = None, None, [], None
    try:
        if ft == 'csv':
            recs = parse_csv(data); method = 'csv parser'
        elif ft == 'json':
            recs = parse_json(data); method = 'json parser'
        elif ft == 'pdf':
            text, method = extract_pdf_text(stored)
            d = parse_report_text(text)
            recs = [(1, 'test', d)]
            for k, kind in (('medications', 'medication'), ('allergies', 'allergy')):
                if d.get(k):
                    for part in re.split(r'[;,]', d[k]):
                        if part.strip() and part.strip().lower() not in ('none', 'nil', 'none recorded'):
                            recs.append((len(recs) + 1, kind, {'patient_id': d.get('patient_id'), 'first_name': d.get('first_name'), 'last_name': d.get('last_name'), 'dob': d.get('dob'), k: part.strip()}))
    except IngestError as e:
        err = str(e)
    except Exception as e:     # parser bug or corrupt file → recorded, never silent
        err = f'Could not read the file: {e}'
    conn.execute("INSERT INTO documents(id,batch_id,patient_id,filename,file_type,size_bytes,sha256,stored_path,doc_type,extracted_text,extraction_method,uploaded_by,uploaded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (doc_id, bid, None, filename, ft, len(data), digest, str(stored), {'pdf': 'Medical report (PDF)', 'csv': 'Data file (CSV)', 'json': 'Data file (JSON)'}.get(ft), text, method, user['id'], now))
    if err:
        conn.execute("UPDATE ingestion_batches SET status='Failed', message=?, extraction_method=? WHERE id=?", (err, method, bid))
        return bid
    dup_of = conn.execute("SELECT b.id FROM ingestion_batches b WHERE b.sha256=? AND b.id<>? AND b.status IN ('Imported','Partially Imported') ORDER BY b.uploaded_at LIMIT 1", (digest, bid)).fetchone()
    seen = set()
    new_ids = set()
    n = 0
    recs = sorted(recs, key=lambda t: (t[1] != 'patient', t[0]))
    for rn, kind, raw in recs:
        n += 1
        if kind == 'unknown':
            conn.execute("INSERT INTO ingestion_records(batch_id,row_no,kind,raw_json,mapped_json,match_status,issues_json,decision,result,result_message) VALUES(?,?,?,?,?,?,?,?,?,?)",
                         (bid, rn, 'unknown', json.dumps(raw), '{}', 'invalid', json.dumps([{'level': 'error', 'msg': 'Unrecognised record type'}]), 'skip', 'failed', 'Unrecognised record type'))
            continue
        d = canonicalise(kind, raw) if ft != 'pdf' else {k: v for k, v in raw.items()}
        if kind == 'medication' and ft == 'pdf':
            pass
        ev = evaluate(conn, kind, d, seen, batch_new_ids=new_ids)
        if kind == 'patient' and ev['match_status'] == 'new' and d.get('patient_id') and re.fullmatch(r'PT-\d{3,6}', d['patient_id']):
            new_ids.add(d['patient_id'])
        if dup_of:
            ev['issues'].append({'level': 'info', 'msg': f'This exact file was already imported in batch {dup_of["id"]}'})
            ev['match_status'], ev['decision'] = 'duplicate', 'skip'
        conn.execute("INSERT INTO ingestion_records(batch_id,row_no,kind,raw_json,mapped_json,match_status,matched_patient_id,candidates_json,issues_json,decision) VALUES(?,?,?,?,?,?,?,?,?,?)",
                     (bid, rn, kind, json.dumps(raw, default=str), json.dumps(d), ev['match_status'], ev['matched_patient_id'], json.dumps(ev['candidates']), json.dumps(ev['issues']), ev['decision']))
        if ev['match_status'] == 'invalid':
            conn.execute("UPDATE ingestion_records SET result='failed', result_message=? WHERE batch_id=? AND row_no=? AND kind=?",
                         ('; '.join(i['msg'] for i in ev['issues'] if i['level'] == 'error'), bid, rn, kind))
    msg = f'Parsed {n} record(s) from {filename}.'
    if dup_of:
        msg += f' Warning: this exact file was already imported in {dup_of["id"]} – all records are marked duplicate.'
    conn.execute("UPDATE ingestion_batches SET n_records=?, extraction_method=?, message=? WHERE id=?", (n, method, msg, bid))
    conn.execute("UPDATE ingestion_batches SET status='Needs Review' WHERE id=?", (bid,))
    return bid


def audit(conn, user, action, pid, entity, detail):
    conn.execute("INSERT INTO audit_log(id,ts,user_id,user_name,role,action,patient_id,entity,detail) VALUES(?,?,?,?,?,?,?,?,?)",
                 (db.next_id(conn, 'AUD'), db.now_iso(), user['id'], user['name'], user['role'], action, pid, entity, detail))


def _new_patient_id(conn, wanted):
    if wanted and re.fullmatch(r'PT-\d{3,6}', wanted) and not conn.execute("SELECT 1 FROM patients WHERE id=?", (wanted,)).fetchone():
        n = int(wanted.split('-')[1])
        cur = conn.execute("SELECT value FROM id_sequences WHERE prefix='PT'").fetchone()
        if not cur or cur[0] < n:
            conn.execute("INSERT INTO id_sequences(prefix,value) VALUES('PT',?) ON CONFLICT(prefix) DO UPDATE SET value=excluded.value", (n,))
        return wanted
    while True:
        pid = db.next_id(conn, 'PT', 1000)
        if not conn.execute("SELECT 1 FROM patients WHERE id=?", (pid,)).fetchone():
            return pid


def _save_record(conn, user, batch, rec):
    """Persist one reviewed record. Returns (entity_id, message). Raises on failure (caller records it)."""
    from .mapping import split_list
    kind, d, bid = rec['kind'], json.loads(rec['mapped_json']), batch['id']
    today = date.today().isoformat()
    now = db.now_iso()
    fname = batch['filename']
    if kind == 'patient' and not rec['matched_patient_id']:
        pid = _new_patient_id(conn, d.get('patient_id'))
        doc = doctor_lookup(conn, d.get('doctor')) or (conn.execute("SELECT u.id FROM users u JOIN user_departments x ON x.user_id=u.id WHERE u.role='doctor' AND x.department=? ORDER BY u.rowid LIMIT 1", (d['department'],)).fetchone() or [None])[0]
        conn.execute("""INSERT INTO patients(id,first_name,last_name,dob,gender,email,mobile,address,ec_name,ec_phone,department,primary_condition,secondary_conditions,
                        previous_surgeries,family_history,ins_provider,policy,coverage,doctor_id,coord_id,registered_on,priority,priority_updated_at,source_batch_id,discharged,draft)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0)""",
                     (pid, d['first_name'], d['last_name'], d['dob'], d.get('gender') or 'Not recorded', d.get('email'), d.get('mobile'), d.get('address'), d.get('ec_name'), d.get('ec_phone'),
                      d['department'], d.get('primary_condition') or 'Not recorded', d.get('secondary_conditions'), d.get('previous_surgeries') or 'None', d.get('family_history') or 'None recorded',
                      d.get('ins_provider'), d.get('policy'), d.get('coverage'), doc, user['id'] if user['role'] == 'coordinator' else None, today, 'med', now, bid))
        conn.execute("INSERT INTO priority_history(patient_id,previous_priority,new_priority,comment,user_id,user_name,user_role,changed_at) VALUES(?,?,?,?,?,?,?,?)",
                     (pid, None, 'med', f'Default priority assigned when the patient was imported (batch {bid})', user['id'], user['name'], user['role'], now))
        _link_patient_lists(conn, pid, d, bid)
        if d.get('care_plan'):
            conn.execute("INSERT INTO care_plans(patient_id,plan_text,start_date,source_batch_id) VALUES(?,?,?,?)", (pid, d['care_plan'], today, bid))
        _hist(conn, pid, today, 'Registration', 'Patient record imported', f'Created from {fname} ({bid}).', bid)
        audit(conn, user, 'Patient imported (new)', pid, bid, f'{d["first_name"]} {d["last_name"]} from {fname}')
        return pid, f'Created patient {pid}'
    pid = rec['matched_patient_id'] or d.get('patient_id')
    if kind == 'patient':
        p = conn.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
        upd = {c: d[k] for k, c in (('email', 'email'), ('mobile', 'mobile'), ('address', 'address'), ('gender', 'gender'), ('ec_name', 'ec_name'), ('ec_phone', 'ec_phone'),
                                    ('primary_condition', 'primary_condition'), ('secondary_conditions', 'secondary_conditions'), ('previous_surgeries', 'previous_surgeries'),
                                    ('family_history', 'family_history'), ('ins_provider', 'ins_provider'), ('policy', 'policy'), ('coverage', 'coverage'))
               if d.get(k) and not (p[c] or '').strip()}
        for c, v in upd.items():
            conn.execute(f"UPDATE patients SET {c}=? WHERE id=?", (v, pid))
        _link_patient_lists(conn, pid, d, bid)
        if d.get('care_plan'):
            r = conn.execute("SELECT plan_text FROM care_plans WHERE patient_id=?", (pid,)).fetchone()
            if not r:
                conn.execute("INSERT INTO care_plans(patient_id,plan_text,start_date,source_batch_id) VALUES(?,?,?,?)", (pid, d['care_plan'], today, bid))
            elif not (r[0] or '').strip():
                conn.execute("UPDATE care_plans SET plan_text=?, source_batch_id=? WHERE patient_id=?", (d['care_plan'], bid, pid))
        _hist(conn, pid, today, 'Update', 'Patient information updated from import', f'Blank fields completed and new list items added from {fname} ({bid}). Existing values were not overwritten.', bid)
        audit(conn, user, 'Patient updated by import', pid, bid, f'{len(upd)} blank field(s) completed from {fname}')
        return pid, f'Updated {pid}'
    p = conn.execute("SELECT doctor_id, department, coord_id FROM patients WHERE id=?", (pid,)).fetchone()
    doc = doctor_lookup(conn, d.get('doctor')) or p['doctor_id']
    if kind == 'consultation':
        eid = db.next_id(conn, 'CON', 4000)
        conn.execute("INSERT INTO consultations(id,patient_id,doctor_id,consult_date,notes,diagnosis,prescription,plan,follow_up,instructions,created_on,source_batch_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                     (eid, pid, doc, d['date'], d['notes'], d.get('diagnosis') or '', d.get('prescription') or '', d.get('plan') or '', d.get('follow_up'), '', now, bid))
        if d.get('follow_up'):
            conn.execute("UPDATE patients SET review_due=? WHERE id=? AND (review_due IS NULL OR review_due < ?)", (d['follow_up'], pid, d['follow_up']))
    elif kind == 'test':
        eid = db.next_id(conn, 'TST', 3000)
        has = bool(d.get('summary'))
        status = d.get('status') if d.get('status') in ('Ordered', 'Scheduled', 'Completed', 'Result Available', 'Reviewed') else ('Result Available' if has else 'Ordered')
        doc_row = conn.execute("SELECT id FROM documents WHERE batch_id=?", (bid,)).fetchone() if batch['file_type'] == 'pdf' else None
        conn.execute("""INSERT INTO diagnostic_tests(id,patient_id,name,ordered_by,ordered_on,status,completed_on,result_on,abnormal,priority,notes,result_summary,result_source,document_id,source_batch_id)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (eid, pid, d['test_name'], doc, d['date'], status, d['date'] if has else None, d['date'] if has else None, 1 if str(d.get('abnormal', '')).lower() in ('1', 'true', 'yes', 'y') else 0,
                      'Routine', f'Imported from {fname}', d.get('summary') if has else None, f'Imported report – {fname} ({bid}); extracted automatically, awaiting clinician review' if has else None,
                      doc_row['id'] if doc_row else None, bid))
        if doc_row:
            conn.execute("UPDATE documents SET patient_id=?, doc_type='Diagnostic report' WHERE id=?", (pid, doc_row['id']))
    elif kind == 'appointment':
        eid = db.next_id(conn, 'APT', 5000)
        conn.execute("INSERT INTO appointments(id,patient_id,doctor_id,dept,appt_date,appt_time,type,status,created_on,notes,source_batch_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                     (eid, pid, doc, p['department'], d['date'], d.get('time') or '09:00', d.get('type') or 'Consultation', d.get('status') or 'Scheduled', now, d.get('notes') or '', bid))
    elif kind == 'referral':
        eid = db.next_id(conn, 'REF', 2000)
        st = d.get('status').title() if d.get('status') and d['status'].title() in ('Pending', 'Booked', 'Completed') else 'Pending'
        conn.execute("INSERT INTO referrals(id,patient_id,referred_to,reason,status,created_on,referred_by,source_batch_id) VALUES(?,?,?,?,?,?,?,?)", (eid, pid, d['referred_to'], d['reason'], st, d.get('date') or today, doc, bid))
    elif kind == 'medication':
        conn.execute("INSERT OR IGNORE INTO medications(patient_id,description,status,source_batch_id) VALUES(?,?, 'Active', ?)", (pid, d['medications'], bid)); eid = f'{pid}/medication'
    elif kind == 'allergy':
        conn.execute("INSERT OR IGNORE INTO allergies(patient_id,substance,source_batch_id) VALUES(?,?,?)", (pid, d['allergies'], bid)); eid = f'{pid}/allergy'
    elif kind == 'history':
        eid = _hist(conn, pid, d['date'], d.get('type') or 'Imported', d['title'], d.get('detail') or '', bid)
    elif kind == 'task':
        eid = db.next_id(conn, 'TSK', 7000)
        conn.execute("INSERT INTO tasks(id,title,patient_id,priority,assignee,created,due,status,kind,source,description,source_batch_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                     (eid, d['title'], pid, d.get('priority') if d.get('priority') in ('high', 'med', 'low') else 'med', p['coord_id'] or doc, today, d['date'], 'New', 'followup', 'Imported file', d.get('notes') or '', bid))
        conn.execute("INSERT INTO task_events(task_id,seq,ts,by_name,text) VALUES(?,?,?,?,?)", (eid, 0, now, user['name'], f'Task imported from {fname} ({bid})'))
    elif kind == 'priority':
        # Same audit trail as a manual change: the confirming Care Coordinator is the person who changes the priority.
        old = conn.execute("SELECT priority FROM patients WHERE id=?", (pid,)).fetchone()['priority']
        new = d['new_priority']
        if old == new:
            return f'{pid}/priority', f'No change – already {PRIORITY_LABEL[new]}'
        comment = f'{d["reason"].strip()} (imported from {fname}, batch {bid})'
        conn.execute("UPDATE patients SET priority=?, priority_updated_at=? WHERE id=?", (new, now, pid))
        cur = conn.execute("INSERT INTO priority_history(patient_id,previous_priority,new_priority,comment,user_id,user_name,user_role,changed_at) VALUES(?,?,?,?,?,?,?,?)",
                           (pid, old, new, comment, user['id'], user['name'], user['role'], now))
        eid = f'PRI-{cur.lastrowid}'
        audit(conn, user, 'Patient priority changed', pid, eid, f'{PRIORITY_LABEL[old]} → {PRIORITY_LABEL[new]}: {comment}')
        return eid, f'Priority changed {PRIORITY_LABEL[old]} → {PRIORITY_LABEL[new]}'
    else:
        raise IngestError(f'Unsupported record type {kind}')
    audit(conn, user, f'Imported {kind}', pid, bid, f'{eid} from {fname}')
    return eid, f'Saved {kind} {eid}'


def _link_patient_lists(conn, pid, d, bid):
    from .mapping import split_list
    for s in split_list(d.get('allergies')):
        conn.execute("INSERT OR IGNORE INTO allergies(patient_id,substance,source_batch_id) VALUES(?,?,?)", (pid, s, bid))
    for s in split_list(d.get('medications')):
        conn.execute("INSERT OR IGNORE INTO medications(patient_id,description,status,source_batch_id) VALUES(?,?,'Active',?)", (pid, s, bid))
    for s in split_list(d.get('diagnoses')):
        conn.execute("INSERT OR IGNORE INTO diagnoses(patient_id,description,source_batch_id) VALUES(?,?,?)", (pid, s, bid))


def _hist(conn, pid, dt, typ, title, detail, bid):
    hid = 'HI-' + db.next_id(conn, 'HIS', 100).split('-')[1]
    conn.execute("INSERT INTO medical_history(id,patient_id,event_date,type,title,detail,source_batch_id) VALUES(?,?,?,?,?,?,?)", (hid, pid, dt, typ, title, detail, bid))
    return hid


def confirm_batch(conn, user, bid):
    """Import every record whose decision is 'import'. Each record is its own savepoint; failures are recorded, never dropped."""
    with db.WRITE_LOCK:
        conn.execute("BEGIN IMMEDIATE")
        try:
            b = conn.execute("SELECT * FROM ingestion_batches WHERE id=?", (bid,)).fetchone()
            if not b:
                raise IngestError('Batch not found')
            if b['status'] != 'Needs Review':
                raise IngestError(f'Batch is {b["status"]} – only batches awaiting review can be confirmed')
            recs = conn.execute("SELECT * FROM ingestion_records WHERE batch_id=? ORDER BY (kind<>'patient'), id", (bid,)).fetchall()
            pend = [r for r in recs if r['decision'] == 'pending']
            if pend:
                raise IngestError(f'{len(pend)} record(s) need a manual patient-match decision before import (rows: ' + ', '.join(str(r['row_no']) for r in pend[:8]) + ')')
            ok = skipped = failed = 0
            new_ids = {}
            for r in recs:
                if r['result'] == 'failed' and r['match_status'] == 'invalid':
                    failed += 1; continue
                if r['decision'] != 'import':
                    conn.execute("UPDATE ingestion_records SET result='skipped', result_message=? WHERE id=?", ('Skipped (' + r['match_status'] + ')', r['id'])); skipped += 1; continue
                rec = dict(r)
                # records that refer to a patient created earlier in the same batch
                conn.execute("SAVEPOINT rec")
                try:
                    eid, msg = _save_record(conn, user, dict(b), rec)
                    if rec['kind'] == 'patient' and not rec['matched_patient_id']:
                        new_ids[(norm_name(json.loads(rec['mapped_json']).get('last_name')), json.loads(rec['mapped_json']).get('dob'))] = eid
                    conn.execute("UPDATE ingestion_records SET result='saved', result_message=?, saved_entity=? WHERE id=?", (msg, eid, r['id']))
                    conn.execute("RELEASE rec"); ok += 1
                except Exception as e:
                    conn.execute("ROLLBACK TO rec"); conn.execute("RELEASE rec")
                    conn.execute("UPDATE ingestion_records SET result='failed', result_message=? WHERE id=?", (str(e), r['id'])); failed += 1
            status = 'Partially Imported' if failed else 'Imported'
            conn.execute("UPDATE ingestion_batches SET status=?, confirmed_by=?, confirmed_at=?, n_imported=?, n_skipped=?, n_failed=?, message=? WHERE id=?",
                         (status, user['id'], db.now_iso(), ok, skipped, failed, f'{ok} imported, {skipped} skipped, {failed} failed/invalid.', bid))
            audit(conn, user, 'Data import confirmed', None, bid, f'{b["filename"]}: {ok} imported, {skipped} skipped, {failed} failed')
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK"); raise
    return {'status': status, 'imported': ok, 'skipped': skipped, 'failed': failed}
