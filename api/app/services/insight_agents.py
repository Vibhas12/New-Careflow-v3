"""Multi-agent phase 6 – on request only.

    insights   "Explain with AI" on Doctor Performance / Executive Overview. Sees the AGGREGATES only (metric values, sample sizes,
               definitions, weekly series, department table) – no patient-level data, no names (a selected doctor is "the selected
               doctor"). Verified: every number must match a figure on the page, cited metrics must exist, no ranking or judging of
               people, no causal claims the figures cannot show, no conclusions from very small samples, phase-2 clinical checks.
    reviewer   "AI safety check" – an optional second opinion on an AI output that is already shown (care-gap wording, patient AI
               summary). Reviews it against the same de-identified facts it was written from. Advisory only: it never changes,
               hides or approves anything; the person decides.
"""
import re
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents import orchestrator, verifier
from app.agents.base import Agent, register
from app.models import AiSummary, CareGapAlert, Patient, User
from app.services.common import utcnow

INSIGHTS, REVIEWER = 'insights', 'reviewer'

INSIGHTS_SYSTEM = """You are the operational-insights agent inside CareFlow. You receive aggregate coordination metrics (counts,
percentages, averages with their sample size n and definition), weekly series and, for the executive view, a department table.
Explain what the figures show for a care-operations audience.

Rules:
- Use only the figures provided and quote numbers exactly as given (you may round averages to whole numbers). Never invent figures.
- These are workflow measures, not clinical quality. Never rank, praise or blame people or teams ("best", "worst", "underperforming").
- Describe patterns; do not claim causes ("because", "due to") - the data cannot show why. You may suggest a question to look into.
- A metric marked "smallSample": true has n below 5. Any statement using it must contain the words "small sample" (for example
  "Attendance was 0%, but this is a small sample of 1 appointment."). Prefer a "caveat" statement for such metrics.
- No clinical advice. statements: 2 to 6, each one or two sentences, kind "observation", "caveat" or "question"; metrics = the keys used."""


class InsightStatement(BaseModel):
    text: str
    kind: Literal['observation', 'caveat', 'question']
    metrics: list[str] = Field(description='Keys of the metrics this statement uses (may be empty for a general caveat).')


class Insights(BaseModel):
    statements: list[InsightStatement]


NUM = re.compile(r'(?<![\w.])(\d+(?:\.\d+)?)(?![\w])')
RANKING = re.compile(r'\b(best|worst|top[- ]performing|bottom|underperform\w*|outperform\w*|poor(ly)?[- ]performing|high[- ]performing|'
                     r'low[- ]performing|blame\w*|fault|lazy|failing|excellent work|good job|bad job)\b', re.I)
CAUSAL = re.compile(r'\b(because|caused by|due to|as a result of|led to|leads to|leading to|thanks to|drove|driven by|resulted in)\b', re.I)
SMALL = re.compile(r'\b(small|few|limited|only|low number|caution|cautious|too few|not enough)\b', re.I)


def _allowed_numbers(context: dict) -> set[float]:
    nums: set[float] = {float(context.get('rangeDays') or 0)}
    for m in context['metrics']:
        for v in (m.get('value'), m.get('n')):
            if isinstance(v, (int, float)):
                nums.add(float(v))
    for vals in context.get('weekly', {}).get('series', {}).values():
        nums |= {float(v) for v in vals if isinstance(v, (int, float))}
    nums.add(float(len(context.get('weekly', {}).get('labels', []))))
    for d in context.get('departments', []):
        nums |= {float(v) for k, v in d.items() if isinstance(v, (int, float))}
    return nums


def _strip_dates(text: str) -> str:
    text = verifier.ISO.sub(' ', text)
    text = verifier.DMY.sub(' ', text)
    text = verifier.D_MON.sub(' ', text)
    return verifier.MON_D.sub(' ', text)


@register
class InsightsAgent(Agent):
    name = INSIGHTS
    label = 'Performance & executive insights'
    system = INSIGHTS_SYSTEM
    instruction = 'Explain these operational figures.'
    output = Insights

    def clean(self, out: Insights, context: dict | None = None) -> Insights:
        for s in out.statements:
            s.text, s.metrics = ' '.join(s.text.split())[:400], sorted(set(m.strip() for m in s.metrics))
        out.statements = [s for s in out.statements if s.text]
        return out

    def verify(self, out: Insights, context: dict) -> list[str]:
        keys = {m['key']: m for m in context['metrics']}
        allowed = _allowed_numbers(context)
        issues = []
        if not 1 <= len(out.statements) <= 6:
            issues.append(f'needs 1-6 statements (has {len(out.statements)})')
        for s in out.statements:
            if unknown := [k for k in s.metrics if k not in keys]:
                issues.append(f'cites a metric that is not on the page ({", ".join(unknown)})')
            for n in NUM.findall(_strip_dates(s.text)):
                v = float(n)
                if not any(abs(v - a) <= 0.5 for a in allowed):
                    issues.append(f'uses a number that is not in the figures ({n})')
            if RANKING.search(s.text):
                issues.append('ranks or judges people')
            if CAUSAL.search(s.text):
                issues.append('claims a cause the figures cannot show')
            small = [keys[k] for k in s.metrics if k in keys and isinstance(keys[k].get('n'), int) and keys[k]['n'] < 5 and keys[k].get('value') is not None]
            if s.kind == 'observation' and small and not SMALL.search(s.text):
                issues.append(f'draws a conclusion from a small sample ({", ".join(f"{m['key']} n={m['n']}" for m in small)})')
            issues += verifier.clinical_advice(s.text) + verifier.grounded_dates(s.text, context) + verifier.sentence_limit(s.text, 2)
        return list(dict.fromkeys(issues))


def explain(db: Session, user: User, page: str, data: dict, scope: str) -> dict:
    """One click → one request. `data` is the metrics payload the page shows; only aggregates are sent."""
    ctx = {'page': page, 'scope': scope, 'rangeDays': {'all': 0}.get(data['range'], int(data['range']) if str(data['range']).isdigit() else 0),
           'metrics': [{**{k: m[k] for k in ('key', 'label', 'value', 'unit', 'n', 'definition')},
                        'smallSample': isinstance(m.get('n'), int) and m['n'] < 5 and m.get('value') is not None} for m in data['kpis']],
           'weekly': data['weekly'], 'departments': data.get('departments', [])}
    r = orchestrator.run(db, user, INSIGHTS, ctx, entity=f'insights:{page}')
    db.commit()
    if not r.ok:
        return {'ok': False, 'status': r.status, 'error': r.error}
    return {'ok': True, 'model': r.model, 'generatedAt': utcnow().isoformat(), 'statements': [s.model_dump() for s in r.output.statements]}


# ---------------------------------------------------------------- safety reviewer (advisory second opinion)
REVIEWER_SYSTEM = """You are the safety reviewer inside CareFlow. Another AI agent wrote the text under "ai_output" from the facts under
"facts". Review it as a careful clinical-governance reviewer would.

Look for: statements not supported by the facts (invented findings, values, dates, events or contact attempts); clinical advice,
diagnosis or interpretation of results; medication or treatment recommendations; anything that sets or changes priority; urgency that
does not match the facts; misleading omissions of an outstanding care gap or pending result; identifying details.
verdict: "no concerns" with an empty list, or "concerns" with each concern stated briefly, a severity ("low" or "high") and, when it
refers to a specific phrase, that phrase copied exactly from ai_output (else ""). Do not rewrite the text."""


class Concern(BaseModel):
    issue: str
    severity: Literal['low', 'high']
    quote: str = Field(description='Exact phrase from ai_output, or "".')


class Review(BaseModel):
    verdict: Literal['no concerns', 'concerns']
    concerns: list[Concern]


@register
class ReviewerAgent(Agent):
    name = REVIEWER
    label = 'AI safety check (second opinion)'
    system = REVIEWER_SYSTEM
    instruction = 'Review this AI output against the facts.'
    output = Review

    def clean(self, out: Review, context: dict | None = None) -> Review:
        for c in out.concerns:
            c.issue, c.quote = ' '.join(c.issue.split())[:300], ' '.join(c.quote.split())[:200]
        out.concerns = [c for c in out.concerns if c.issue][:8]
        return out

    def verify(self, out: Review, context: dict) -> list[str]:
        issues = []
        if out.verdict == 'concerns' and not out.concerns:
            issues.append('says there are concerns but lists none')
        if out.verdict == 'no concerns' and out.concerns:
            issues.append('says no concerns but lists some')
        text = ' '.join(str(v) for v in _flatten(context['ai_output'])).lower()
        norm = lambda s: ' '.join(s.lower().split())
        for c in out.concerns:
            if c.quote and norm(c.quote) not in norm(text):
                issues.append(f'quotes a phrase that is not in the AI output ("{c.quote[:60]}")')
        return issues


def _flatten(x):
    if isinstance(x, dict):
        for v in x.values():
            yield from _flatten(v)
    elif isinstance(x, list):
        for v in x:
            yield from _flatten(v)
    elif isinstance(x, str):
        yield x


def _review(db: Session, user: User, facts: dict, ai_output, patient: Patient | None, entity: str) -> dict:
    r = orchestrator.run(db, user, REVIEWER, {'facts': facts, 'ai_output': ai_output}, patient=patient, entity=entity)
    db.commit()
    if not r.ok:
        return {'ok': False, 'status': r.status, 'error': r.error}
    out: Review = r.output
    return {'ok': True, 'verdict': out.verdict, 'concerns': [c.model_dump() for c in out.concerns], 'model': r.model, 'checkedAt': utcnow().isoformat()}


def review_alert(db: Session, user: User, a: CareGapAlert) -> dict:
    from app.services import recommendation_agent as ra
    if not ra.is_current(a):
        raise ValueError('There is no current AI wording on this alert to check')
    p = db.get(Patient, a.patient_id)
    return _review(db, user, ra.build_context(a, p), {'recommendation': a.ai_text, 'rationale': a.ai_rationale, 'task_title': a.ai_task_title},
                   p, f'review:{a.id}')


def review_summary(db: Session, user: User, patient_id: str) -> dict:
    from app.agents.context import patient_context
    ctx = patient_context(db, user, patient_id)                 # scoped: 404 / 403 outside the user's patients
    row = db.get(AiSummary, ctx.patient.id)
    if row is None or not row.payload or row.source_hash != ctx.fingerprint:
        raise ValueError('There is no current AI summary for this patient to check')
    return _review(db, user, ctx.llm, row.payload, ctx.patient, f'review:summary:{ctx.patient.id}')
