"""Pure parsing for Data Import (no database): CSV / JSON / PDF → (row, kind, raw dict), field mapping and date parsing.

Ported unchanged in behaviour from the V2 prototype (backend/ingest.py).
"""
import csv
import io
import json
import os
import re
import subprocess
import tempfile
from datetime import date
from pathlib import Path

DEPTS = ['Cardiology', 'Neurology', 'Oncology', 'Orthopedics', 'General Medicine', 'Mental Health']
APPT_STATUS = ['Scheduled', 'Confirmed', 'Completed', 'Missed', 'Cancelled']
NONE_WORDS = {'', 'none', 'none recorded', 'n/a', 'nil', 'not recorded'}

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
MONTHS = {m: i + 1 for i, m in enumerate(['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'])}


class IngestError(Exception):
    pass


def norm_key(k) -> str:
    return re.sub(r'[^a-z0-9]+', '_', str(k).strip().lower()).strip('_')


def norm_name(s) -> str:
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def split_list(s) -> list[str]:
    return [p.strip() for p in str(s or '').split(';') if p.strip() and p.strip().lower() not in NONE_WORDS]


def parse_date(s) -> str | None:
    """ISO, dd/mm/yyyy (UK order), dd-mm-yyyy, '5 Mar 2024'. Returns an ISO string or None."""
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


def detect_type(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip('.')


def parse_csv(data: bytes):
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
    return [(rn, KIND_ALIASES.get(norm_key(r.get('record_type') or r.get('kind') or 'patient')) or 'unknown', r) for rn, r in rows]


def parse_json(data: bytes):
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


def extract_pdf_text(path: Path) -> tuple[str, str]:
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
    if len(text.strip()) < 25:
        try:
            with tempfile.TemporaryDirectory() as td:
                _run(['pdftoppm', '-r', '200', '-png', str(path), os.path.join(td, 'p')], 120)
                parts = [_run(['tesseract', str(img), '-', '--psm', '6'], 120).stdout.decode('utf-8', 'replace') for img in sorted(Path(td).glob('p*.png'))[:10]]
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


def parse_report_text(text: str) -> dict:
    """Rule-based extraction of a diagnostic report. Returns a canonical mapped dict (no clinical interpretation)."""
    lines = [l.rstrip() for l in text.replace('\r', '').split('\n')]
    kv = {}
    for i, l in enumerate(lines):
        m = HEAD.match(l)
        if m and m[1].strip().lower() not in kv:
            kv[m[1].strip().lower()] = (m[2].strip(), i)

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
    out['patient_id'] = first('patient id', 'patient ref', 'mrn') or (m[1] if m else None)
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


def canonicalise(kind: str, raw: dict) -> dict:
    """raw keys → canonical keys using aliases; keep only fields relevant to the kind."""
    out, wanted = {}, set(KIND_FIELDS.get(kind, []))
    for k, v in raw.items():
        c = CANON.get(norm_key(k))
        if kind == 'patient' and c == 'date':
            continue
        if c in wanted and v not in (None, ''):
            if isinstance(v, list):
                v = '; '.join(str(x) for x in v)
            elif isinstance(v, dict):
                v = json.dumps(v)
            out[c] = v if isinstance(v, bool) else str(v).strip()
    if 'name' in raw and 'first_name' not in out and kind in KIND_FIELDS:
        parts = str(raw['name']).split()
        if len(parts) >= 2:
            out['first_name'], out['last_name'] = parts[0], parts[-1]
    if 'patient_id' in out:
        out['patient_id'] = out['patient_id'].strip().upper()
    return out
