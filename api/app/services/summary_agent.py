"""Patient summary agent (multi-agent phase 3) – writes the AI Summary tab with Google Gemini, on request only.

Pipeline for one click on "Generate AI summary" (POST /api/assistant/patients/{id}/summary/ai):
    Context agent (code)  → scoped, numbered, de-identified facts          agents/context.py
    Summary agent (LLM)   → overview + narrative sections citing [n]       this module, through agents/orchestrator.run()
    Verifier (code)       → sources exist, nothing important dropped,
                            phase-2 content checks on every statement      verify() below + agents/verifier.py
The suggested next steps are NOT written by this agent: they stay rule-based (care-gap alerts, with the recommendation
agent's wording where current) so the approve buttons are never driven by free text.
The result is stored per patient with the Context agent's fingerprint; it is hidden as soon as the records change.
"""
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents import limits, orchestrator, verifier
from app.agents.base import Agent, register
from app.agents.context import SECTIONS, PatientContext, patient_context
from app.models import AiSummary, User
from app.services.common import utcnow

NAME = 'summary'

SYSTEM = """You are the patient-summary agent inside CareFlow, a care-coordination tool used by care coordinators and doctors.
You receive recorded facts about one patient. Each fact has a section, a kind (fact / suggestion / missing) and the numbers of the
source records it comes from. Rewrite them into a clear, concise summary for the care team.

Rules:
- Use only the facts provided. Never add findings, values, dates, names, history or events that are not in them.
- Every statement of kind "fact" or "suggestion" must list the source numbers of the facts it is based on (use only numbers given).
- Keep "missing" information as kind "missing" (no sources needed) - never drop it.
- Never drop an outstanding care gap, a pending result or referral, an allergy or a missing-information item. You may merge
  facts that say the same thing and remove repetition.
- Do not diagnose, interpret results clinically, recommend or change medication or treatment, or set or change the priority.
- Do not write next actions: those are handled separately by the rule engine.
- overview: one to three statements giving the most important current picture (outstanding care gaps and pending results first).
- One or two short sentences per statement. UK English, plain and calm. Patient names are not provided; say "the patient"."""


class Statement(BaseModel):
    text: str = Field(description='One or two short sentences.')
    kind: Literal['fact', 'suggestion', 'missing']
    sources: list[int] = Field(description='Source numbers this statement is based on (empty only for kind "missing").')


class PatientSummary(BaseModel):
    overview: list[Statement] = Field(description='1-3 statements: the most important current picture.')
    context: list[Statement]
    history: list[Statement]
    gaps: list[Statement]
    appointments: list[Statement]
    results: list[Statement]


PARTS = ('overview', *SECTIONS)


@register
class SummaryAgent(Agent):
    name = NAME
    label = 'Patient AI summary'
    system = SYSTEM
    instruction = 'Write the patient summary from these recorded facts.'
    output = PatientSummary
    temperature = 0.2
    max_output_tokens = 4096

    def clean(self, out: PatientSummary, context: dict | None = None) -> PatientSummary:
        for part in PARTS:
            items = []
            for s in getattr(out, part):
                s.text = ' '.join(s.text.split())[:400]
                s.sources = sorted(set(s.sources))
                if s.text:
                    items.append(s)
            setattr(out, part, items)
        return out

    def verify(self, out: PatientSummary, context: dict) -> list[str]:
        valid = {s['n'] for s in context['sources']}
        # the records themselves contain a few unsourced statements (e.g. "No pending diagnostic results.") – restating one is fine
        unsourced_ok = {(f['section'], f['kind']) for f in context['facts'] if not f['sources']}
        # 3 sentences per statement, or as many as the longest recorded fact in that section (a restated consultation note)
        longest: dict[str, int] = {}
        for f in context['facts']:
            longest[f['section']] = max(longest.get(f['section'], 3), verifier.sentence_count(f['text']))
        issues: list[str] = []
        if not 1 <= len(out.overview) <= 3:
            issues.append(f'overview must have 1-3 statements (has {len(out.overview)})')
        if sum(len(getattr(out, p)) for p in PARTS) > 40:
            issues.append('too many statements')
        for part in PARTS:
            for s in getattr(out, part):
                if s.kind in ('fact', 'suggestion') and not s.sources and (part, s.kind) not in unsourced_ok:
                    issues.append(f'{part}: a statement has no source')
                if bad := [n for n in s.sources if n not in valid]:
                    issues.append(f'{part}: cites a source that does not exist ({", ".join(map(str, bad))})')
                issues += [f'{part}: {i}' for i in verifier.check_wording(s.text, context)]
                issues += [f'{part}: {i}' for i in verifier.sentence_limit(s.text, longest.get(part, 3))]
        issues += coverage(out, context)
        return list(dict.fromkeys(issues))


def coverage(out: PatientSummary, context: dict) -> list[str]:
    """Nothing important may be dropped: every source behind a care gap or a pending result / referral must still be cited
    in that section, and no missing-information item may disappear."""
    issues = []
    facts = context['facts']
    for sec, label in (('gaps', 'care gap'), ('results', 'pending result or referral')):
        need = {n for f in facts if f['section'] == sec and f['kind'] != 'missing' for n in f['sources']}
        need -= {n for f in facts if f['section'] == sec and f['text'].startswith(('No outstanding care gaps', 'No pending')) for n in f['sources']}
        have = {n for s in getattr(out, sec) for n in s.sources}
        if lost := sorted(need - have):
            issues.append(f'drops a {label} (source {", ".join(map(str, lost))})')
    if (m_in := sum(f['kind'] == 'missing' for f in facts)) > (m_out := sum(s.kind == 'missing' for p in PARTS for s in getattr(out, p))):
        issues.append(f'drops missing-information items ({m_in} in the records, {m_out} in the summary)')
    return issues


# ---------------------------------------------------------------- service
def _ai_block(row: AiSummary | None, ctx: PatientContext) -> dict:
    """What the AI Summary tab shows next to the template: status plus, when current, the AI statements."""
    if not limits.is_enabled(NAME):
        return {'status': 'off', 'reason': limits.unavailable_reason(NAME)}
    if row is None:
        return {'status': 'none'}
    current = bool(row.payload) and row.source_hash == ctx.fingerprint
    if current and not row.error:
        return {'status': 'ready', 'model': row.model, 'generatedAt': row.generated_at.isoformat() if row.generated_at else None, **row.payload}
    if row.error:
        st = 'withheld' if row.error.startswith(orchestrator.WITHHELD) else 'error'
        out = {'status': st, 'error': row.error}
        if current:                                   # an earlier summary for the same records is still valid – keep showing it
            out.update(status='ready', model=row.model, generatedAt=row.generated_at.isoformat() if row.generated_at else None, lastError=row.error, **row.payload)
        return out
    return {'status': 'stale'}


def summary(db: Session, user: User, patient_id: str) -> dict:
    """Template summary (no LLM) plus the stored AI summary when it still matches the records. Never calls the model."""
    ctx = patient_context(db, user, patient_id)
    return {**ctx.brief, 'ai': _ai_block(db.get(AiSummary, ctx.patient.id), ctx)}


def generate(db: Session, user: User, patient_id: str) -> tuple[dict, bool]:
    """One click → one model request. Returns (summary response, ok). Raises AgentDisabled / AgentLimited (503 / 429)."""
    ctx = patient_context(db, user, patient_id)
    r = orchestrator.run(db, user, NAME, ctx.llm, patient=ctx.patient, entity=f'summary:{ctx.patient.id}')
    row = db.get(AiSummary, ctx.patient.id) or AiSummary(patient_id=ctx.patient.id)
    if r.ok:
        out: PatientSummary = r.output
        row.payload = {p: [s.model_dump() for s in getattr(out, p)] for p in PARTS}
        row.source_hash, row.model, row.generated_at, row.generated_by, row.error, row.error_at = ctx.fingerprint, r.model, utcnow(), user.id, None, None
    else:
        row.error, row.error_at = (r.error or 'AI summary failed')[:1000], utcnow()
    db.add(row)
    db.flush()
    return {**ctx.brief, 'ai': _ai_block(row, ctx)}, r.ok
