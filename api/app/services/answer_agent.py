"""AI Care Assistant – "Ask AI" (multi-agent phase 4). On request only: one click → one Gemini request.

    Orchestrator (code)  route the question: a named / selected patient → that patient's facts; otherwise → the worklist
                         of every patient in the user's scope. Patients become "Patient A, B, …", staff "Staff 1 (doctor)…"
                         and the user "you" – in the facts AND in the question – before anything is sent.
    Context (code)       numbered, de-identified facts (agents/context.py for one patient; worklist_context() below)
    Answer agent (LLM)   statements citing source numbers, plus up to 3 drafted tasks / reminders
    Verifier (code)      sources exist, aliases exist, phase-2 content checks on every statement, title and message;
                         leak checks across every patient in scope (orchestrator)
Only after verification are aliases mapped back to names for display. Drafted actions become AssistantProposal rows in
status Proposed – nothing is created or sent until a person approves. On any failure the template answer is used.
"""
import re
import string
from datetime import timedelta
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import limits, orchestrator, verifier
from app.agents.base import Agent, register
from app.agents.context import patient_context
from app.agents.privacy import scrub
from app.models import Appointment, AssistantProposal, CareGapAlert, DiagnosticTest, Patient, Referral, Task, User
from app.services.common import fmt_d, next_id, today, utcnow

NAME = 'answer'
PRI = {'high': 'High', 'med': 'Medium', 'low': 'Low'}
ROLE = {'doctor': 'doctor', 'coordinator': 'care coordinator', 'admin': 'administrator'}
MAX_ACTIONS = 3

SYSTEM = """You are the question-answering agent inside CareFlow, a care-coordination tool used by care coordinators and doctors.
You receive a user's question and numbered, de-identified facts from the records the user is allowed to see. Patients are called
"Patient A", "Patient B", …; staff are "Staff 1 (doctor)" etc.; the person asking is "you".

Rules:
- Answer only from the facts. If they do not contain the answer, say so in a statement of kind "missing" - never guess.
- Every statement of kind "fact" or "suggestion" lists the source numbers it is based on (only numbers given) and the patient alias it
  is about ("" when it covers several patients).
- Refer to patients only by their alias (e.g. "Patient A"). Never invent names, IDs, dates, values, events or contact attempts.
- Do not diagnose, interpret results clinically, recommend or change medication or treatment, or set or change priority.
- actions: only when the user asks for a task or reminder, or when a care gap clearly needs a coordination step. At most 3. Each is a
  draft for a person to approve: a task title (imperative, max 100 characters) or a reminder message to the patient (plain, max 300
  characters, no clinical content). due_in_days: 0-14.
- intro: one or two sentences answering the question directly. Keep statements short (one or two sentences). UK English, plain and calm."""


class AnswerStatement(BaseModel):
    text: str
    kind: Literal['fact', 'suggestion', 'missing']
    sources: list[int] = Field(description='Source numbers (empty only for kind "missing").')
    patient: str = Field(description='Patient alias such as "Patient A", or "" when not about one patient.')


class DraftAction(BaseModel):
    patient: str = Field(description='Patient alias, e.g. "Patient A".')
    type: Literal['task', 'reminder']
    title: str = Field(description='Imperative task title, or a short label for the reminder.')
    message: str = Field(description='For a reminder: the message to the patient. For a task: "".')
    due_in_days: int


class Answer(BaseModel):
    intro: str
    statements: list[AnswerStatement]
    actions: list[DraftAction]


@register
class AnswerAgent(Agent):
    name = NAME
    label = 'Assistant answers (Ask AI)'
    system = SYSTEM
    instruction = 'Answer the question from these facts.'
    output = Answer
    max_output_tokens = 4096

    def prompt(self, context: dict) -> str:
        import json
        q = context['question']
        facts = {k: v for k, v in context.items() if k != 'question'}
        return f'Question: {q}\n\nFacts (JSON):\n' + json.dumps(facts, ensure_ascii=False)

    def clean(self, out: Answer) -> Answer:
        out.intro = ' '.join(out.intro.split())[:500]
        for s in out.statements:
            s.text, s.sources, s.patient = ' '.join(s.text.split())[:400], sorted(set(s.sources)), s.patient.strip()
        out.statements = [s for s in out.statements if s.text]
        for a in out.actions:
            a.title, a.message, a.patient = ' '.join(a.title.split())[:100], ' '.join(a.message.split())[:300], a.patient.strip()
        return out

    def verify(self, out: Answer, context: dict) -> list[str]:
        valid = {s['n'] for s in context['sources']}
        aliases = set(context['patients'])
        issues: list[str] = []
        if not out.intro:
            issues.append('empty answer')
        issues += verifier.check_wording(out.intro, context) + verifier.sentence_limit(out.intro, 3)
        if len(out.statements) > 25:
            issues.append('too many statements')
        for s in out.statements:
            if s.kind in ('fact', 'suggestion') and not s.sources:
                issues.append('a statement has no source')
            if bad := [n for n in s.sources if n not in valid]:
                issues.append(f'cites a source that does not exist ({", ".join(map(str, bad))})')
            if s.patient and s.patient not in aliases:
                issues.append(f'refers to an unknown patient ({s.patient})')
            issues += verifier.check_wording(s.text, context) + verifier.sentence_limit(s.text, 3)
        if len(out.actions) > MAX_ACTIONS:
            issues.append(f'more than {MAX_ACTIONS} drafted actions')
        for a in out.actions:
            if a.patient not in aliases:
                issues.append(f'drafts an action for an unknown patient ({a.patient or "none"})')
            if not a.title or (a.type == 'reminder' and not a.message):
                issues.append(f'incomplete drafted {a.type}')
            if not 0 <= a.due_in_days <= 14:
                issues.append('drafted action due date out of range')
            issues += [f'drafted {a.type}: {i}' for i in verifier.check_wording(f'{a.title}. {a.message}', context)]
        mentioned = set(re.findall(r'\bPatient [A-Z]{1,2}\b', ' '.join([out.intro, *[s.text for s in out.statements], *[a.title + ' ' + a.message for a in out.actions]])))
        if unknown := sorted(mentioned - aliases):
            issues.append(f'mentions an unknown patient ({", ".join(unknown)})')
        return list(dict.fromkeys(issues))


# ---------------------------------------------------------------- context building (code only)
def _alias(i: int) -> str:
    letters = string.ascii_uppercase
    return 'Patient ' + (letters[i] if i < 26 else letters[i // 26 - 1] + letters[i % 26])


class Scope:
    """What the Answer agent may see, plus everything needed to map aliases back after verification."""

    def __init__(self, db: Session, user: User):
        self.db, self.user = db, user
        self.alias: dict[str, Patient] = {}               # 'Patient A' -> Patient
        self.sources: list[dict] = []                     # [{n, label, ref, ts}] – ref / ts stay on the server
        self.facts: list[dict] = []
        self.staff: dict[str, str] = {}                   # staff name -> alias
        for k, (uid, name, role) in enumerate(db.execute(select(User.id, User.name, User.role).order_by(User.id)).all(), 1):
            self.staff[name] = 'you' if uid == user.id else f'Staff {k} ({ROLE.get(role, role)})'

    def src(self, ref: str, label: str, ts) -> int:
        for s in self.sources:
            if s['ref'] == ref:
                return s['n']
        self.sources.append({'n': len(self.sources) + 1, 'ref': ref, 'label': label, 'ts': ts.isoformat() if ts else None})
        return len(self.sources)

    def staff_alias(self, text: str) -> str:
        for name in sorted(self.staff, key=len, reverse=True):
            if name and name in text:
                text = text.replace(name, self.staff[name])
            last = name.split()[-1] if name else ''
            if len(last) > 2:                                # "Dr. Wilson" / "Dr Wilson" in a question
                text = re.sub(rf'\bDr\.?\s+{re.escape(last)}\b', self.staff[name], text)
        return text

    def clean(self, text: str, p: Patient | None, alias: str) -> str:
        return scrub(self.staff_alias(text or ''), p, alias) if p else self.staff_alias(text or '')

    def question(self, text: str) -> str:
        q = self.staff_alias(text)
        for a, p in self.alias.items():
            q = scrub(q, p, a)
        return q

    def llm(self, question: str, route: str) -> dict:
        return {'question': self.question(question), 'today': fmt_d(today()), 'scope': route, 'patients': sorted(self.alias),
                'sources': [{'n': s['n'], 'label': s['label']} for s in self.sources], 'facts': self.facts}


def patient_scope(db: Session, user: User, p: Patient) -> Scope:
    """One patient: the Context agent's facts (phase 3) plus the rule-based next steps."""
    sc = Scope(db, user)
    ctx = patient_context(db, user, p.id)
    sc.alias['Patient A'] = ctx.patient
    sc.sources = [dict(e) for e in ctx.brief['evidence']]
    for sec in ('context', 'history', 'gaps', 'appointments', 'results', 'next'):
        for f in ctx.brief['sections'][sec]:
            sc.facts.append({'patient': 'Patient A', 'section': sec, 'kind': f['kind'], 'text': sc.clean(f['text'], ctx.patient, 'Patient A'), 'sources': f['sources']})
    return sc


def worklist_scope(db: Session, user: User, pool: list[Patient]) -> Scope:
    """Every patient in the user's scope: priority, open care gaps, appointments (missed in the last 14 days, upcoming 30),
    tests not yet reviewed, open referrals and open tasks – each fact citing its record."""
    sc, T = Scope(db, user), today()
    ids = [p.id for p in pool]

    def by(model, *where) -> dict[str, list]:
        out = {pid: [] for pid in ids}
        for x in db.execute(select(model).where(model.patient_id.in_(ids), *where)).scalars():
            out[x.patient_id].append(x)
        return out
    alerts = by(CareGapAlert, CareGapAlert.status == 'Open')
    appts = by(Appointment, Appointment.appt_date >= T - timedelta(days=14), Appointment.appt_date <= T + timedelta(days=30))
    tests = by(DiagnosticTest, DiagnosticTest.status != 'Reviewed')
    refs = by(Referral, Referral.status.not_in(('Completed', 'Cancelled')))
    tasks = by(Task, Task.status != 'Completed')
    names = dict(db.execute(select(User.id, User.name)).all())
    for i, p in enumerate(pool):
        a = _alias(i)
        sc.alias[a] = p
        add = lambda section, text, ref, label, ts, kind='fact': sc.facts.append(
            {'patient': a, 'section': section, 'kind': kind, 'text': sc.clean(text, p, a), 'sources': [sc.src(ref, label, ts)]})
        add('patient', f'{a}: {p.department or "department not recorded"}, primary condition {p.primary_condition or "not recorded"}, '
                       f'priority {PRI[p.priority]}, assigned doctor {names.get(p.doctor_id, "not recorded")}.', p.id, 'Patient record', p.registered_on)
        for x in alerts[p.id]:
            add('care gap', f'{a}: [{x.category}, {PRI[x.priority]}] {x.reason}', x.id, 'Care-gap alert', x.first_seen)
        for x in sorted(appts[p.id], key=lambda x: x.appt_date):
            if x.status == 'Missed' or (x.status in ('Scheduled', 'Confirmed') and x.appt_date >= T):
                add('appointment', f'{a}: {x.type} on {fmt_d(x.appt_date)} {x.appt_time or ""} with {names.get(x.doctor_id, "a doctor")} – {x.status}.',
                    x.id, 'Appointment', x.created_on or x.appt_date)
        for x in tests[p.id]:
            add('test', f'{a}: {x.name} – {x.status}' + (', values outside the reference range' if x.abnormal and x.status == 'Result Available' else '')
                + (f', ordered {fmt_d(x.ordered_on)}' if x.ordered_on else '') + '.', x.id, 'Diagnostic test', x.result_on or x.ordered_on)
        for x in refs[p.id]:
            add('referral', f'{a}: referral to {x.referred_to} – {x.status}, created {fmt_d(x.created_on)}.', x.id, 'Referral', x.created_on)
        for x in tasks[p.id]:
            add('task', f'{a}: task "{x.title}" assigned to {names.get(x.assignee, "nobody")}, due {fmt_d(x.due)} – {x.status}.', x.id, 'Task', x.created)
    return sc


# ---------------------------------------------------------------- run
def _display(text: str, sc: Scope) -> str:
    for a in sorted(sc.alias, key=len, reverse=True):
        p = sc.alias[a]
        text = re.sub(rf'\b{a}\b', f'{p.full_name} ({p.id})', text)
    inv = {v: k for k, v in sc.staff.items() if v != 'you'}
    for alias in sorted(inv, key=len, reverse=True):
        text = text.replace(alias, inv[alias])
    return text


def ask_ai(db: Session, user: User, text: str, patient: Patient | None, pool: list[Patient]) -> dict | None:
    """Returns the assistant message dict (intro, blocks, trace, patientId) or None when the AI could not answer
    (the caller then uses the template answer). Raises nothing for LLM problems; AgentDisabled / AgentLimited propagate."""
    route = 'patient' if patient else 'worklist'
    sc = patient_scope(db, user, patient) if patient else worklist_scope(db, user, pool)
    trace = [f'Orchestrator: “Ask AI” – routed to the {"patient" if patient else "worklist"} context'
             + (f' for {patient.full_name} ({patient.id})' if patient else f' ({len(sc.alias)} authorised patient(s))') + '.',
             f'Context Agent: {len(sc.facts)} de-identified fact(s) citing {len(sc.sources)} source record(s); patients and staff replaced by aliases.']
    r = orchestrator.run(db, user, NAME, sc.llm(text, route), patient=patient if patient else None,
                         patients=None if patient else list(sc.alias.values()), entity=f'chat:{route}')
    if not r.ok:
        trace.append(f'Answer Agent: {r.status} – {r.error}')
        return {'failed': r.error, 'status': r.status, 'trace': trace}
    out: Answer = r.output
    trace.append(f'Answer Agent ({r.model}): {len(out.statements)} statement(s), {len(out.actions)} drafted action(s).')
    trace.append('Verifier: passed – every statement cites an existing source; no clinical advice, priority change or invented detail.')
    statements = [{'text': _display(s.text, sc), 'kind': s.kind, 'sources': s.sources,
                   'patientId': sc.alias[s.patient].id if s.patient in sc.alias else None} for s in out.statements]
    blocks = [{'type': 'answer', 'statements': statements,
               'evidence': [{'n': s['n'], 'label': s['label'], 'ref': s['ref'], 'ts': s['ts']} for s in sc.sources
                            if any(s['n'] in st['sources'] for st in statements)]}]
    prop_ids = []
    for a in out.actions:
        p = sc.alias[a.patient]
        prop = AssistantProposal(id=next_id(db, 'PR', 100), created_by=user.id, created_at=utcnow(), patient_id=p.id, type=a.type,
                                 title=_display(a.title, sc), assignee=p.coord_id or user.id, due=today() + timedelta(days=a.due_in_days),
                                 priority=p.priority, channel='SMS' if a.type == 'reminder' else None,
                                 message=_display(a.message, sc).replace(f'{p.full_name} ({p.id})', p.first_name) if a.type == 'reminder' else None,
                                 status='Proposed', rationale=f'Drafted by the AI answer agent ({r.model}) from a chat question by {user.name}.')
        db.add(prop)
        db.flush()
        prop_ids.append(prop.id)
    if prop_ids:
        blocks.append({'type': 'proposals', 'proposalIds': prop_ids})
        trace.append(f'Next-Best-Action: {len(prop_ids)} draft(s) saved as Proposed – nothing happens until an authorised user approves.')
    pids = {st['patientId'] for st in statements if st['patientId']}
    return {'intro': _display(out.intro, sc), 'blocks': blocks, 'trace': trace, 'ai': True, 'model': r.model,
            'patientId': patient.id if patient else (pids.pop() if len(pids) == 1 else None)}


def available() -> bool:
    return limits.is_enabled(NAME)
