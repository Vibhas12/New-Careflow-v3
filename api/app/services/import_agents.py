"""Data Import agents (multi-agent phase 5) – on request only, inside the human review step. They never import anything.

    import_extract  "Extract with AI" on a PDF report row: reads the report text and suggests the REPORT fields only
                    (test name, report date, findings, abnormal flag). Patient identity stays with the rule-based extractor and
                    the ID-first matching – identity lines are removed and names / IDs / contacts scrubbed before sending, and
                    the call is blocked if anything identifying remains.
    import_map      "Map columns with AI" on a CSV / JSON batch: suggests a CareFlow field (or "ignore") for each column the
                    alias table does not know. The model sees column names and value SHAPES only – never values.

Verification (code): extracted test name, date and every value must appear in the document, findings must be mostly the
document's own words, the abnormal flag must be supported by the wording, and the phase-2 content checks apply; mappings
must name a real unknown column and a field valid for the record types present, with no field used twice.
Suggestions are stored (ingestion_records.ai_suggestion / ingestion_batches.ai_mapping) and only change a record when the
reviewer selects Apply – which re-runs the normal matching and duplicate checks. Mapping fills empty fields only.
"""
import re
import time
from datetime import date
from types import SimpleNamespace
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import orchestrator, verifier
from app.agents.base import Agent, register
from app.agents.privacy import scrub
from app.ingest import pipeline
from app.ingest.parsing import CANON, HEAD, KIND_FIELDS, IngestError, norm_key, parse_date
from app.models import IngestionBatch, IngestionRecord, Patient, User
from app.services.common import audit, utcnow

EXTRACT, MAP = 'import_extract', 'import_map'
IDENTITY_LABELS = {'patient', 'patient name', 'name', 'dob', 'date of birth', 'patient id', 'patient ref', 'mrn', 'nhs number', 'nhs no',
                   'address', 'phone', 'mobile', 'telephone', 'tel', 'email', 'contact', 'next of kin', 'emergency contact', 'gender', 'sex', 'age',
                   # clinician names are not needed for the report fields either (the doctor is matched by the rule-based pipeline)
                   'requested by', 'reported by', 'consultant', 'clinician', 'referred by', 'gp', 'doctor', 'signed', 'authorised by'}
ABNORMAL_CUES = re.compile(r'\babnormal|outside (the )?(normal |reference )?range|\braised\b|\belevated\b|\bhigh\b|\blow\b|\bpositive\b|'
                           r'\bdetected\b|\bflag(ged)?\b|\(h\)|\(l\)|\bdeficien|\bsuggestive\b|\bconsistent with\b', re.I)
NORMAL_CUES = re.compile(r'\bnormal\b|within (the )?(normal |reference )?(range|limits)|\bunremarkable\b|\bno (significant )?abnormalit|'
                         r'\bnegative\b|\bno acute\b|\bnot detected\b', re.I)
FIELD_HELP = {
    'patient_id': 'patient ID (PT-####)', 'first_name': 'first name', 'last_name': 'surname', 'dob': 'date of birth', 'gender': 'gender',
    'email': 'email address', 'mobile': 'phone number', 'address': 'postal address', 'ec_name': 'emergency contact name',
    'ec_phone': 'emergency contact phone', 'department': 'department / specialty', 'primary_condition': 'primary condition',
    'secondary_conditions': 'secondary conditions', 'allergies': 'allergies (; separated)', 'medications': 'medications (; separated)',
    'diagnoses': 'previous diagnoses', 'previous_surgeries': 'previous surgeries', 'family_history': 'family history',
    'doctor': 'doctor name or ID', 'care_plan': 'care / treatment plan', 'ins_provider': 'insurance provider', 'policy': 'policy number',
    'coverage': 'coverage type', 'date': 'the record date (consultation, appointment, report, event or due date)', 'time': 'appointment time',
    'type': 'appointment or event type', 'status': 'status', 'notes': 'notes', 'diagnosis': 'diagnosis', 'prescription': 'prescription',
    'plan': 'plan', 'follow_up': 'follow-up / review date', 'test_name': 'test or report name', 'summary': 'result summary / findings',
    'abnormal': 'abnormal flag (yes/no)', 'referred_to': 'referral destination', 'reason': 'reason / comment', 'title': 'task or event title',
    'detail': 'event detail', 'priority': 'task priority', 'new_priority': 'new patient priority (High/Medium/Low)',
}


# ---------------------------------------------------------------- document extraction agent
EXTRACT_SYSTEM = """You are the document-extraction agent inside CareFlow's Data Import review. You receive the text of one diagnostic
report (identity details have been removed) and the fields a rule-based extractor found. Extract the report fields.

Rules:
- Copy, do not interpret: test_name and report_date exactly as they appear in the document; findings in the document's own words
  (you may shorten, at most 600 characters). Leave a field empty ("") when the document does not state it.
- abnormal: "yes" only when the document itself SAYS a result is abnormal / outside the range / raised / low / flagged; "no" only when it
  says normal / within range / unremarkable; otherwise "not stated". Never compare a value with its reference range yourself - that is a
  clinical judgement for the doctor.
- Never add a diagnosis, interpretation, advice, names or identifiers.
- notes_for_reviewer: one short sentence about anything ambiguous (e.g. two dates), or ""."""


class ReportFields(BaseModel):
    test_name: str
    report_date: str = Field(description='As written in the document, or "".')
    findings: str
    abnormal: Literal['yes', 'no', 'not stated']
    notes_for_reviewer: str


def _norm(s: str) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', (s or '').lower()).strip()


@register
class ExtractionAgent(Agent):
    name = EXTRACT
    label = 'Import: document extraction'
    system = EXTRACT_SYSTEM
    instruction = 'Extract the report fields from this document.'
    output = ReportFields

    def clean(self, out: ReportFields, context: dict | None = None) -> ReportFields:
        out.test_name, out.report_date = ' '.join(out.test_name.split())[:120], out.report_date.strip()[:40]
        out.findings, out.notes_for_reviewer = ' '.join(out.findings.split())[:600], ' '.join(out.notes_for_reviewer.split())[:200]
        if context and (note := self.drop_unsupported_flag(out, context['document'])):
            out.notes_for_reviewer = f'{out.notes_for_reviewer} {note}'.strip()
        return out

    @staticmethod
    def drop_unsupported_flag(out: ReportFields, doc: str) -> str | None:
        """An abnormal / normal flag the document does not state is removed (one field), not a reason to withhold the rest."""
        if (out.abnormal == 'yes' and not ABNORMAL_CUES.search(doc)) or (out.abnormal == 'no' and not NORMAL_CUES.search(doc)):
            flag, out.abnormal = out.abnormal, 'not stated'
            return f'The AI\'s "{"abnormal" if flag == "yes" else "normal"}" flag was removed – the document does not state it; the doctor decides.'
        return None

    def verify(self, out: ReportFields, context: dict) -> list[str]:
        doc = context['document']
        ctx = {'document': doc}
        nd = _norm(doc)
        issues = []
        if not (out.test_name or out.findings):
            issues.append('nothing extracted')
        if out.test_name and _norm(out.test_name) not in nd:
            issues.append(f'test name "{out.test_name}" does not appear in the document')
        if out.report_date:
            if not parse_date(out.report_date):
                issues.append(f'report date "{out.report_date}" is not a recognisable date')
            issues += verifier.grounded_dates(out.report_date, ctx)
        if out.findings:
            words = [w for w in _norm(out.findings).split() if len(w) >= 4]
            if words and sum(w in nd.split() for w in words) / len(words) < 0.6:
                issues.append('findings are not taken from the document')
            issues += verifier.check_wording(out.findings, ctx)
        if out.abnormal == 'yes' and not ABNORMAL_CUES.search(doc):         # still a hard check – the flag is dropped BEFORE verify
            issues.append('abnormal flag not supported by the document')
        if out.abnormal == 'no' and not NORMAL_CUES.search(doc):
            issues.append('"normal" flag not supported by the document')
        issues += verifier.clinical_advice(out.notes_for_reviewer, ctx)
        return list(dict.fromkeys(issues))


def _identity(db: Session, rec: IngestionRecord):
    """Whose identifiers to remove: the matched patient if any, plus what the rule extractor read from the document."""
    m = rec.mapped or {}
    dob = parse_date(m.get('dob'))
    pseudo = SimpleNamespace(id=m.get('patient_id') or '', first_name=m.get('first_name') or '', last_name=m.get('last_name') or '',
                             full_name=' '.join(x for x in (m.get('first_name'), m.get('last_name')) if x), dob=date.fromisoformat(dob) if dob else None,
                             ec_name=None, address=None, email=None, mobile=None)
    real = db.get(Patient, rec.matched_patient_id) if rec.matched_patient_id else None
    return [x for x in (real, pseudo) if x is not None]


def scrub_document(text: str, people: list) -> str:
    lines = []
    for line in (text or '').replace('\r', '').split('\n'):
        m = HEAD.match(line)
        lines.append('[identity line removed]' if m and m[1].strip().lower() in IDENTITY_LABELS else line)
    out = '\n'.join(lines)
    for p in people:
        out = scrub(out, p)
    return out[:6000]


def extract(db: Session, user: User, rec: IngestionRecord) -> bool:
    b = db.get(IngestionBatch, rec.batch_id)
    if b.status != 'Needs Review':
        raise IngestError('This batch has already been finalised')
    if b.file_type != 'pdf' or rec.kind != 'test':
        raise IngestError('AI extraction is available for the report row of a PDF import')
    from app.models import Document
    d = db.execute(select(Document).where(Document.batch_id == b.id)).scalar()
    if not d or not (d.extracted_text or '').strip():
        raise IngestError('No document text is available for this batch')
    t = time.perf_counter()
    people = _identity(db, rec)
    doc = scrub_document(d.extracted_text, people)
    m = rec.mapped or {}
    ctx = {'document': doc, 'rule_extracted': {'test_name': m.get('test_name') or '', 'date': m.get('date') or '', 'summary': (m.get('summary') or '')[:600]}}
    real = people[0] if people and isinstance(people[0], Patient) else None
    pre = [orchestrator.timed_step('Document scrub', t, f'{doc.count("[identity line removed]")} identity line(s) removed · {len(doc):,} characters kept')]
    r = orchestrator.run(db, user, EXTRACT, ctx, patient=real, patients=None if real else [p for p in people if p.full_name or p.id], entity=f'import:{rec.id}',
                         pre_steps=pre)
    now = utcnow().isoformat()
    if r.ok:
        out: ReportFields = r.output
        fields = {k: v for k, v in {'test_name': out.test_name, 'date': parse_date(out.report_date) if out.report_date else '', 'summary': out.findings,
                                     'abnormal': {'yes': 'yes', 'no': 'no'}.get(out.abnormal, '')}.items() if v}
        rec.ai_suggestion = {'status': 'ready', 'fields': fields, 'notes': out.notes_for_reviewer, 'model': r.model, 'at': now, 'applied': False}
    else:
        rec.ai_suggestion = {'status': r.status, 'error': r.error, 'issues': r.issues, 'at': now}
    audit(db, user, 'AI import extraction', entity=b.id, detail=f'row {rec.row_no}: {r.status}' + (f' · {r.model}' if r.model else ''))
    db.commit()
    return r.ok


def apply_extraction(db: Session, user: User, rec: IngestionRecord) -> None:
    s = rec.ai_suggestion or {}
    if s.get('status') != 'ready' or s.get('applied'):
        raise IngestError('There is no AI suggestion to apply for this row')
    fields = dict(s['fields'])
    rec.ai_suggestion = {**s, 'applied': True, 'applied_by': user.id, 'applied_at': utcnow().isoformat()}
    db.flush()
    audit(db, user, 'AI import suggestion applied', entity=rec.batch_id, detail=f'row {rec.row_no}: {", ".join(fields)}')
    pipeline.review_record(db, user, rec, fields=fields, patient_id=None, decision=None)        # re-checks match + duplicates, commits


# ---------------------------------------------------------------- column-mapping agent
MAP_SYSTEM = """You are the column-mapping agent inside CareFlow's Data Import review. A CSV or JSON file has columns that CareFlow's
alias table does not recognise. For each one you get the column name, the record types it appears in, and the SHAPE of its values
(no actual values). Suggest which CareFlow field it holds, or "" to ignore it.

Rules:
- Only use fields listed for the record types the column appears in. Never map two columns to the same field.
- When unsure, use "" (ignore) - a person reviews every suggestion. reason: one short phrase (e.g. "name and date shape match")."""


class ColumnMapping(BaseModel):
    header: str
    field: str = Field(description='A CareFlow field name from the allowed list, or "" to ignore the column.')
    reason: str


class Mappings(BaseModel):
    mappings: list[ColumnMapping]


@register
class MappingAgent(Agent):
    name = MAP
    label = 'Import: column mapping'
    system = MAP_SYSTEM
    instruction = 'Suggest a CareFlow field for each unrecognised column.'
    output = Mappings

    def clean(self, out: Mappings, context: dict | None = None) -> Mappings:
        for m in out.mappings:
            m.header, m.field, m.reason = m.header.strip(), m.field.strip(), ' '.join(m.reason.split())[:150]
        return out

    def verify(self, out: Mappings, context: dict) -> list[str]:
        cols = {c['header']: c for c in context['columns']}
        issues, used, seen = [], {}, set()
        for m in out.mappings:
            if m.header not in cols:
                issues.append(f'maps a column that is not in the file or already recognised ({m.header})')
                continue
            if m.header in seen:
                issues.append(f'maps column {m.header} twice')
            seen.add(m.header)
            if m.field:
                allowed = {f for k in cols[m.header]['kinds'] for f in context['targets'].get(k, [])}
                if m.field not in allowed:
                    issues.append(f'field "{m.field}" is not valid for {", ".join(cols[m.header]["kinds"])} records ({m.header})')
                if m.field in used:
                    issues.append(f'maps {used[m.field]} and {m.header} to the same field ({m.field})')
                used[m.field] = m.header
        return list(dict.fromkeys(issues))


def _shape(values: list) -> str:
    vals = [str(v).strip() for v in values if v not in (None, '') and str(v).strip()]
    if not vals:
        return 'always empty'
    if all(parse_date(v) for v in vals):
        return 'date'
    if all(re.fullmatch(r'\d{1,2}:\d{2}', v) for v in vals):
        return 'time (HH:MM)'
    if all(re.fullmatch(r'PT-\d{3,6}', v, re.I) for v in vals):
        return 'patient ID format (PT-####)'
    if all(re.fullmatch(r'[\w.+-]+@[\w-]+\.[\w.-]+', v) for v in vals):
        return 'email-like'
    if all(sum(c.isdigit() for c in v) >= 10 and re.fullmatch(r'[\d\s()+.-]+', v) for v in vals):
        return 'phone-number-like'
    if all(v.lower() in ('yes', 'no', 'y', 'n', 'true', 'false', '0', '1') for v in vals):
        return 'yes/no'
    if all(re.fullmatch(r'-?\d+(\.\d+)?', v) for v in vals):
        return 'number'
    distinct, avg = len({v.lower() for v in vals}), sum(map(len, vals)) / len(vals)
    if distinct <= 5 and len(vals) >= 3 and avg <= 20:
        return f'category ({distinct} distinct short values)'
    if all(len(v.split()) in (2, 3) and all(w[:1].isupper() for w in v.split()) for v in vals) and avg <= 30:
        return 'two or three capitalised words (name-like)'
    return 'short text (≤ 30 characters)' if avg <= 30 else f'free text (about {int(avg)} characters)'


def unknown_columns(db: Session, b: IngestionBatch) -> list[dict]:
    recs = list(db.execute(select(IngestionRecord).where(IngestionRecord.batch_id == b.id, IngestionRecord.kind != 'unknown')).scalars())
    cols: dict[str, dict] = {}
    for r in recs:
        for k, v in (r.raw or {}).items():
            if norm_key(k) in CANON or norm_key(k) in ('record_type', 'kind'):
                continue
            c = cols.setdefault(k, {'header': k, 'kinds': set(), 'values': []})
            c['kinds'].add(r.kind)
            c['values'].append(v)
    out = []
    for c in cols.values():
        filled = sum(1 for v in c['values'] if v not in (None, '') and str(v).strip())
        out.append({'header': c['header'], 'kinds': sorted(c['kinds']), 'shape': _shape(c['values']),
                    'filled': f'{round(100 * filled / max(1, len(c["values"])))}% of rows'})
    return sorted(out, key=lambda c: c['header'])


def suggest_mapping(db: Session, user: User, b: IngestionBatch) -> bool:
    if b.status != 'Needs Review':
        raise IngestError('This batch has already been finalised')
    if b.file_type not in ('csv', 'json'):
        raise IngestError('AI column mapping is available for CSV and JSON imports')
    t = time.perf_counter()
    cols = unknown_columns(db, b)
    if not cols:
        raise IngestError('Every column in this file is already recognised')
    pre = [orchestrator.timed_step('Column profiling', t, f'{len(cols)} unrecognised column(s) · names and value shapes only')]
    kinds = sorted({k for c in cols for k in c['kinds']})
    known = sorted({k for r in db.execute(select(IngestionRecord.raw).where(IngestionRecord.batch_id == b.id)).scalars() for k in (r or {}) if norm_key(k) in CANON})
    ctx = {'columns': cols, 'known_columns': known, 'targets': {k: KIND_FIELDS[k] for k in kinds if k in KIND_FIELDS},
           'field_help': {f: FIELD_HELP.get(f, f) for k in kinds for f in KIND_FIELDS.get(k, [])}}
    r = orchestrator.run(db, user, MAP, ctx, entity=f'import:{b.id}', pre_steps=pre)
    now = utcnow().isoformat()
    if r.ok:
        b.ai_mapping = {'status': 'ready', 'mappings': [m.model_dump() for m in r.output.mappings], 'columns': cols, 'model': r.model, 'at': now, 'applied': False}
    else:
        b.ai_mapping = {'status': r.status, 'error': r.error, 'issues': r.issues, 'columns': cols, 'at': now}
    audit(db, user, 'AI import column mapping', entity=b.id, detail=f'{len(cols)} unknown column(s): {r.status}' + (f' · {r.model}' if r.model else ''))
    db.commit()
    return r.ok


def apply_mapping(db: Session, user: User, b: IngestionBatch) -> int:
    """Fill EMPTY fields of every record still in review from the mapped columns; each changed record is re-checked."""
    s = b.ai_mapping or {}
    if b.status != 'Needs Review':
        raise IngestError('This batch has already been finalised')
    if s.get('status') != 'ready' or s.get('applied'):
        raise IngestError('There is no AI column mapping to apply for this batch')
    mapping = {m['header']: m['field'] for m in s['mappings'] if m['field']}
    changed = 0
    b.ai_mapping = {**s, 'applied': True, 'applied_by': user.id, 'applied_at': utcnow().isoformat()}
    audit(db, user, 'AI import column mapping applied', entity=b.id, detail=', '.join(f'{h} → {f}' for h, f in mapping.items()) or 'nothing mapped')
    db.commit()
    for rec in list(db.execute(select(IngestionRecord).where(IngestionRecord.batch_id == b.id, IngestionRecord.kind != 'unknown').order_by(IngestionRecord.id)).scalars()):
        fields = {}
        for h, f in mapping.items():
            v = (rec.raw or {}).get(h)
            if f in KIND_FIELDS.get(rec.kind, []) and v not in (None, '') and str(v).strip() and not (rec.mapped or {}).get(f):
                fields[f] = str(v).strip().upper() if f == 'patient_id' else str(v).strip()
        if fields:
            pipeline.review_record(db, user, rec, fields=fields, patient_id=None, decision=None)
            changed += 1
    return changed
