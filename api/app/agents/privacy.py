"""Data minimisation for every agent.

deidentify()  – replaces the patient's names and IDs inside free text before it is sent to the model.
find_leaks()  – returns the KINDS of identifier found in a text (never the values), used by the orchestrator twice:
                on the input (a hit blocks the call – nothing is sent) and on the output (a hit withholds the answer).
"""
import re

from app.models import Patient

PATIENT_ID = re.compile(r'\bPT-\d{3,6}\b', re.I)
EMAIL = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')
PHONE_CANDIDATE = re.compile(r'\+?\d[\d\s().-]{7,}\d')


def deidentify(text: str, p: Patient | None, replacement: str = 'the patient') -> str:
    if not text:
        return text
    if p:
        if p.id:
            text = re.sub(rf'\b{re.escape(p.id)}\b', replacement, text, flags=re.I)
        for s in sorted({p.full_name, p.first_name, p.last_name} - {None}, key=len, reverse=True):
            if s and len(s) > 1:                              # whole words only: "Ann" must not touch "Annual"
                text = re.sub(rf'(?<!\w){re.escape(s)}(?!\w)', replacement, text, flags=re.I)
    return PATIENT_ID.sub('a patient', text) if replacement != 'the patient' else PATIENT_ID.sub('the patient', text)


def scrub(text: str, p: Patient | None, replacement: str = 'the patient') -> str:
    """deidentify() plus removal of contact details, date of birth and address from free text (consultation notes,
    imported document extracts) so that a single stray identifier does not block the whole request."""
    if not text:
        return text
    text = deidentify(text, p, replacement)
    text = EMAIL.sub('[email removed]', text)
    text = PHONE_CANDIDATE.sub(lambda m: '[number removed]' if sum(c.isdigit() for c in m.group()) >= 10 else m.group(), text)
    if p is not None:
        for f in _dob_forms(p):
            text = text.replace(f, '[date of birth removed]')
        if p.address and len(p.address) > 8:
            text = re.sub(re.escape(p.address), '[address removed]', text, flags=re.I)
        if p.ec_name and len(p.ec_name) > 2:
            text = re.sub(re.escape(p.ec_name), 'the emergency contact', text, flags=re.I)
    return text


def _dob_forms(p: Patient) -> set[str]:
    if not p.dob:
        return set()
    d = p.dob
    return {d.isoformat(), d.strftime('%d/%m/%Y'), f'{d.day} {d.strftime("%b")} {d.year}', f'{d.day} {d.strftime("%B")} {d.year}'}


def find_leaks_many(text: str, patients: list[Patient]) -> list[str]:
    """Leak check across several patients (worklist questions): generic identifiers plus each patient's full name, ID,
    date of birth and contact details. Single first or last names are not checked here – with many patients they collide
    with ordinary words; every text sent was already built through deidentify()/scrub() for its own patient."""
    found = set(find_leaks(text))
    low = text.lower()
    for p in patients:
        if p.full_name and p.full_name.lower() in low:
            found.add('patient or contact name')
        if p.id and re.search(rf'\b{re.escape(p.id)}\b', text, re.I):
            found.add('patient ID')
        if any(f in text for f in _dob_forms(p)):
            found.add('date of birth')
        if p.email and p.email.lower() in low:
            found.add('email address')
    return sorted(found)


def find_leaks(text: str, p: Patient | None = None) -> list[str]:
    """Kinds of identifying information present in `text` – e.g. ['patient name', 'phone number']. Empty = clean."""
    if not text:
        return []
    found = []
    if PATIENT_ID.search(text):
        found.append('patient ID')
    if EMAIL.search(text):
        found.append('email address')
    if any(sum(c.isdigit() for c in m.group()) >= 10 for m in PHONE_CANDIDATE.finditer(text)):    # dates have fewer digits
        found.append('phone number')
    if p is not None:
        names = [s for s in (p.first_name, p.last_name, p.ec_name) if s and len(s) > 2]
        if any(re.search(rf'\b{re.escape(n)}\b', text, re.I) for n in names):
            found.append('patient or contact name')
        if any(f in text for f in _dob_forms(p)):
            found.append('date of birth')
        if p.address and len(p.address) > 8 and p.address.lower() in text.lower():
            found.append('address')
    return found
