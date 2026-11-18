"""Safety & grounding verifier (multi-agent phase 2) – deterministic code checks, no LLM, run on every AI output.

Each check returns a list of short, human-readable problems (empty = passes). The orchestrator withholds any output with
problems: nothing is shown or stored on the record, the rule template stays on screen, and the problems go to agent_runs.issues.

    clinical_advice()   diagnosis, clinical interpretation of results, prescribing or medication / dose changes
    priority_change()   the model must never set or change a patient's priority
    action_claims()     claims that something was already done, or contact attempts that are not in the facts
    grounded_dates()    every explicit date must appear in the facts
    grounded_values()   every measured value / dose (number + unit) must appear in the facts
    grounded_tests()    every known test name must appear in the facts
    responsible_role()  work that needs a doctor must name a doctor
    urgency_matches()   wording must not contradict the rule's priority
    sentence_limit()    keep the recommendation short

Checks are deliberately conservative: a false alarm costs one "Regenerate" click; a missed one could mislead the care team.
"""
import json
import re
from datetime import date

from app.core.catalog import TEST_TYPES

MONTHS = {m: i + 1 for i, m in enumerate(['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'])}
_MON = r'(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?'
ISO = re.compile(r'\b(\d{4})-(\d{2})-(\d{2})\b')
DMY = re.compile(r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b')
D_MON = re.compile(rf'\b(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MON}(?:\s+(\d{{4}}))?\b', re.I)
MON_D = re.compile(rf'\b{_MON}\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b', re.I)
VALUE = re.compile(r'\b(\d+(?:\.\d+)?)\s?(mg|mcg|µg|g|ml|l|mmol/mol|mmol/l|mmol|iu|units?|mmhg|kg|bpm|%)(?![a-z])', re.I)

CLINICAL = [
    (r'\bdiagnos(e|es|ed|is|ing)\b', 'gives or suggests a diagnosis'),
    (r'\b(likely|probably|possibly)\s+(has|have|is|indicates|suffering)\b', 'speculates about the patient\'s condition'),
    (r'\b(consistent with|indicative of|suggestive of|in keeping with|points to)\b', 'interprets findings clinically'),
    (r'\b(result|results|value|values|reading|levels?)\s+(is|are|look|looks|seem|seems|appear|appears)\s+'
     r'(normal|fine|ok|okay|reassuring|good|bad|concerning|worrying|alarming|serious|dangerous|high|low|elevated|raised)\b', 'interprets results clinically'),
    (r'\b(nothing|no need)\s+to\s+worry\b|\bno\s+(further\s+)?(clinical\s+)?action\s+(is\s+)?(needed|required)\b', 'gives clinical reassurance'),
    (r'\bprescrib(e|es|ing)\b', 'recommends prescribing'),             # 'prescribed' (a description of the record) is fine
    (r'\b(start|stop|stopping|starting|discontinue|withhold|increase|decrease|reduce|double|halve|adjust|titrate|switch|change)\s+'
     r'(the\s+|their\s+|his\s+|her\s+)?(dose|dosage|medication|medicine|tablets?|insulin|treatment|therapy|prescription)\b', 'recommends a medication or treatment change'),
    (r'\b(take|taking)\s+(an?\s+)?(extra|additional|more|less|fewer)\b', 'gives dosing advice'),
    (r'\bdose\s+(of|to)\s+\d', 'gives dosing advice'),
    (r'\b(refer|send)\s+(the patient\s+)?(to\s+)?(a&e|a & e|emergency|the emergency department)\b|\bcall\s+(999|911|an ambulance)\b', 'recommends emergency care'),
]
PRIORITY = re.compile(r'\b(change|set|raise|lower|upgrade|downgrade|escalate|increase|reduce|mark)\b[^.;]{0,30}\bpriority\b|'
                      r'\bpriority\b[^.;]{0,20}\b(to|should be)\s+(high|medium|med|low)\b', re.I)
CLAIMS = [
    (r'\bI\s*(\'ve|have|\'ll|will|am|\'m)\b', 'speaks as if the AI took action'),
    (r'\b(has|have|had)\s+(already\s+)?been\s+(contacted|called|phoned|booked|rebooked|scheduled|reminded|notified|informed|seen|reviewed|sent)\b',
     'claims an action was already done'),
    (r'\b(did not|didn\'t|does not|doesn\'t)\s+(answer|respond|reply|pick up)\b|\bno answer\b|\bunreachable\b|\bleft\s+(a\s+)?(voice\s?mail|message)\b|'
     r'\b(declined|refused)\b', 'mentions a contact attempt'),
]
URGENT = re.compile(r'\b(urgent|urgently|immediately|emergency|asap|as soon as possible|straight away|right away|without delay|today)\b', re.I)
RELAXED = re.compile(r'\b(no rush|not urgent|non-urgent|when convenient|at your convenience|whenever|low priority|no hurry|can wait)\b', re.I)
DOCTOR = re.compile(r'\b(doctor|dr\.?|clinician|consultant|gp|physician|responsible clinician)\b', re.I)


def _flat(context: dict) -> str:
    return json.dumps(context, ensure_ascii=False).lower()


def _year(y: str | None) -> int | None:
    return int(y) if y else None


def _dates(text: str) -> list[tuple[int | None, int, int]]:
    """(year or None, month, day) for every explicit date in the text."""
    out = []
    for y, m, d in ISO.findall(text):
        out.append((int(y), int(m), int(d)))
    for d, m, y in DMY.findall(text):
        out.append((int(y), int(m), int(d)))
    for d, mon, y in D_MON.findall(text):
        out.append((_year(y), MONTHS[mon[:3].lower()], int(d)))
    for mon, d, y in MON_D.findall(text):
        out.append((_year(y), MONTHS[mon[:3].lower()], int(d)))
    return [x for x in out if 1 <= x[1] <= 12 and 1 <= x[2] <= 31]


def _valid(y, m, d) -> bool:
    try:
        date(y or 2000, m, d)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------- individual checks
def _new_matches(pattern, text: str, context: dict | None) -> bool:
    """True when the pattern matches text that is NOT already in the facts (restating a recorded note is allowed)."""
    facts = _flat(context) if context else ''
    rx = pattern if isinstance(pattern, re.Pattern) else re.compile(pattern, re.I)
    return any(m.group(0).lower() not in facts for m in rx.finditer(text))


def clinical_advice(text: str, context: dict | None = None) -> list[str]:
    return sorted({msg for pat, msg in CLINICAL if _new_matches(pat, text, context)})


def priority_change(text: str, context: dict | None = None) -> list[str]:
    return ['tries to set or change the patient\'s priority'] if _new_matches(PRIORITY, text, context) else []


def action_claims(text: str, context: dict) -> list[str]:
    facts = _flat(context)
    out = set()
    for pat, msg in CLAIMS:
        for m in re.finditer(pat, text, re.I):
            if m.group(0).lower() not in facts:              # allowed when the facts say so (e.g. "was scheduled for …")
                out.add(msg)
    return sorted(out)


def grounded_dates(text: str, context: dict) -> list[str]:
    known = _dates(json.dumps(context, ensure_ascii=False))
    full = {(y, m, d) for y, m, d in known if y}
    day_month = {(m, d) for _, m, d in known}
    bad = [(y, m, d) for y, m, d in _dates(text) if _valid(y, m, d) and ((y and (y, m, d) not in full) or (not y and (m, d) not in day_month))]
    return [f'mentions a date that is not in the facts ({d}/{m}' + (f'/{y})' if y else ')') for y, m, d in bad[:3]]


def grounded_values(text: str, context: dict) -> list[str]:
    facts = re.sub(r'\s+', '', _flat(context))
    bad = {f'{n}{u}' for n, u in VALUE.findall(text) if f'{n}{u}'.lower().replace(' ', '') not in facts}
    return [f'mentions a value or dose that is not in the facts ({v})' for v in sorted(bad)[:3]]


def grounded_tests(text: str, context: dict) -> list[str]:
    facts, low = _flat(context), text.lower()
    bad = [t for t in TEST_TYPES if re.search(rf'\b{re.escape(t.lower())}\b', low) and t.lower() not in facts]
    return [f'mentions a test that is not in the facts ({t})' for t in bad]


def responsible_role(text: str, role: str | None) -> list[str]:
    if role and role.lower() == 'doctor' and not DOCTOR.search(text):
        return ['does not hand the decision to the responsible doctor']
    return []


def urgency_matches(text: str, priority: str | None) -> list[str]:
    p = (priority or '').lower()
    if p == 'low' and URGENT.search(text):
        return ['sounds urgent although the rule priority is Low']
    if p == 'high' and RELAXED.search(text):
        return ['plays down a High-priority gap']
    return []


def sentence_limit(text: str, limit: int) -> list[str]:
    n = len([s for s in re.split(r'(?<![Dd]r\.)(?<![Mm]rs\.)(?<=[.!?])\s+', text.strip()) if s])
    return [f'too long ({n} sentences, at most {limit})'] if n > limit else []


def check_wording(text: str, context: dict, *, priority: str | None = None, role: str | None = None) -> list[str]:
    """All content checks for a piece of AI wording that the care team will read."""
    return (clinical_advice(text, context) + priority_change(text, context) + action_claims(text, context) + grounded_dates(text, context)
            + grounded_values(text, context) + grounded_tests(text, context) + urgency_matches(text, priority))
