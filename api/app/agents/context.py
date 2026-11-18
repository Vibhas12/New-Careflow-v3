"""Context agent (multi-agent phase 3) – deterministic code, NO LLM.

Gathers a patient's records for the other agents, strictly inside the requesting user's scope, and turns them into the
only form an agent may see: a numbered, de-identified fact list.

    patient_context(db, user, patient_id) -> PatientContext
        .patient   the Patient row (used by the orchestrator's privacy checks, never sent)
        .brief     the template summary (services/assistant.brief) – sections of facts citing numbered sources
        .llm       what is sent to the model: {'sources': [{n, label}], 'facts': [{section, kind, text, sources}]}
        .fingerprint  hash of .llm – unchanged records → same fingerprint → a stored AI summary is still current

Scope: brief() resolves the patient with get_visible_patient(), so a doctor gets 404 for another doctor's patient and an
administrator gets 403 – the same rules as every other patient endpoint.
De-identification: names and IDs → "the patient"; contact details, date of birth and address removed from free text
(consultation notes, document extracts); staff names → their role. Source record IDs are not sent – only their labels.
"""
import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.privacy import scrub
from app.models import Patient, User

SECTIONS = ('context', 'history', 'gaps', 'appointments', 'results')      # narrative sections the summary agent may write
ROLE = {'doctor': 'a doctor', 'coordinator': 'a care coordinator', 'admin': 'an administrator'}


@dataclass
class PatientContext:
    patient: Patient
    brief: dict
    llm: dict
    fingerprint: str


def _staff_to_roles(db: Session, text: str) -> str:
    for name, role in db.execute(select(User.name, User.role)).all():
        if name and name in text:
            text = text.replace(name, ROLE.get(role, 'a staff member'))
    return text


def patient_context(db: Session, user: User, patient_id: str) -> PatientContext:
    from app.services.assistant import brief                 # local import: assistant imports the agents package
    b = brief(db, user, patient_id)                          # scoped (404 / 403 outside the user's patients)
    p = db.get(Patient, b['patientId'])
    clean = lambda t: scrub(_staff_to_roles(db, t), p)
    facts = [{'section': sec, 'kind': f['kind'], 'text': clean(f['text']), 'sources': f['sources']}
             for sec in SECTIONS for f in b['sections'][sec]]
    llm = {'sources': [{'n': e['n'], 'label': e['label']} for e in b['evidence']], 'facts': facts}
    fp = hashlib.sha256(json.dumps(llm, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return PatientContext(p, b, llm, fp)
