"""Care-gap recommendation agent – words the 'Recommended next action' for an alert with Google Gemini.

Division of labour (unchanged safety model):
  * the deterministic rule engine (services/care_gaps.py) decides THAT there is a gap, its priority and its evidence;
  * this agent only WORDS the next coordination step, a one-line rationale and a task title;
  * a person still approves, modifies or dismisses – nothing is executed by the model.

Data minimisation: the model receives de-identified facts only – category, rule, priority, reason, evidence text,
department, primary condition and the rule's template action. No names, IDs, dates of birth or contact details are sent
(patient names and IDs that appear inside rule text are replaced before sending, and the orchestrator blocks the call if
any identifier is still present).

Runs through the shared agent layer (app/agents): kill switch, per-user limits, run log, output checks.
On demand only: word() is called solely from POST /api/care-gaps/{id}/recommendation, i.e. when a person clicks
"Generate / Regenerate with AI". No scan, import, list view or scheduled job calls the model.
"""
import hashlib
import json

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents import limits, orchestrator
from app.agents.base import Agent, register
from app.agents.privacy import deidentify as _deidentify
from app.models import CareGapAlert, Patient, User
from app.services.care_gaps import RULES
from app.services.common import utcnow

NAME = 'recommendation'

SYSTEM = """You are the recommendation-wording agent inside CareFlow, a care-coordination tool used by care coordinators and doctors.
A deterministic rule engine has already detected a care gap for one patient and attached the evidence. Your only job is to word the
next coordination step for the care team.

Rules:
- Use only the facts provided. Never invent findings, values, dates, history or contact attempts.
- Do not diagnose, interpret results clinically, recommend, start, stop or change any medication or treatment, and do not set or change
  the patient's priority.
- Recommend one concrete coordination action: contact the patient, book or rebook, chase a service, confirm attendance, or ask the
  responsible doctor to review. When clinical judgement is needed, say the doctor should review - do not suggest what they should decide.
- recommendation: one or two short sentences addressed to the care team, starting with the action.
- rationale: one sentence linking the action to the evidence.
- task_title: an imperative task title of at most 80 characters.
- UK English, plain and calm wording. Patient names are not provided; refer to "the patient"."""


class Recommendation(BaseModel):
    recommendation: str = Field(description='One or two short sentences, starting with the coordination action.')
    rationale: str = Field(description='One sentence linking the action to the evidence.')
    task_title: str = Field(description='Imperative task title, at most 80 characters.')


@register
class RecommendationAgent(Agent):
    name = NAME
    label = 'Care-gap recommendation wording'
    system = SYSTEM
    instruction = 'Word the recommended next action for this care gap.'
    output = Recommendation

    def clean(self, rec: Recommendation) -> Recommendation:
        rec.recommendation, rec.rationale, rec.task_title = (s.strip() for s in (rec.recommendation, rec.rationale, rec.task_title))
        rec.task_title = rec.task_title[:80]
        rec.recommendation, rec.rationale = rec.recommendation[:600], rec.rationale[:400]
        return rec

    def verify(self, rec: Recommendation, context: dict) -> list[str]:
        # phase 2 (safety & grounding verifier) adds the grounding and clinical-advice checks here
        return ['empty recommendation or task title'] if not rec.recommendation or not rec.task_title else []


def source_hash(a: CareGapAlert) -> str:
    """Fingerprint of the facts the wording depends on – a change hides the wording until someone regenerates it."""
    facts = json.dumps([a.rule, a.priority, a.reason, [e.get('text') for e in a.evidence or []], a.action.get('title')], sort_keys=True)
    return hashlib.sha256(facts.encode()).hexdigest()


def is_current(a: CareGapAlert) -> bool:
    """Stored wording may be used: the agent is switched on and the wording matches the alert's current facts."""
    return bool(a.ai_text) and a.ai_source_hash == source_hash(a) and limits.is_enabled(NAME)


def build_context(a: CareGapAlert, p: Patient | None) -> dict:
    cat, name, desc = RULES.get(a.rule, (a.category, a.rule_name, ''))
    d = lambda s: _deidentify(s, p)
    return {
        'care_gap_category': cat, 'rule': name, 'rule_definition': desc, 'priority': {'high': 'High', 'med': 'Medium', 'low': 'Low'}[a.priority],
        'reason': d(a.reason), 'evidence': [d(e.get('text', '')) for e in a.evidence or []],
        'patient_context': {'department': p.department if p else None, 'primary_condition': p.primary_condition if p else None},
        'rule_template_action': {'task_title': d(a.action.get('title', '')), 'text': d(a.action.get('text', '')), 'due': a.action.get('due')},
        'responsible_role': 'Doctor' if a.rule == 'results_review' else 'Care Coordinator',
    }


def word(db: Session, a: CareGapAlert, user: User, *, commit: bool = True) -> bool:
    """Word one alert at a person's request. Stores the result (or the error) on the alert; returns False on failure.
    Raises limits.AgentDisabled / AgentLimited (nothing is sent or stored on the alert) – the route turns them into 503 / 429."""
    p = db.get(Patient, a.patient_id)
    h = source_hash(a)
    r = orchestrator.run(db, user, NAME, build_context(a, p), patient=p, entity=a.id)
    if not r.ok:
        a.ai_error = (r.error or 'AI wording failed')[:500]
        if commit:
            db.commit()
        return False
    rec: Recommendation = r.output
    a.ai_text, a.ai_rationale, a.ai_task_title = rec.recommendation, rec.rationale, rec.task_title
    a.ai_model, a.ai_generated_at, a.ai_source_hash, a.ai_error = r.model, utcnow(), h, None
    if commit:
        db.commit()
    return True


def status(a: CareGapAlert) -> str:
    """On demand only – nothing is generated automatically, so there is no 'pending' state.
    'ready' – wording matches the current facts · 'off' – no key, or the agent is switched off (stored wording hidden too) ·
    'error' – the last requested attempt failed · 'stale' – wording exists but the alert's facts changed (offer Regenerate) ·
    'none' – never requested (offer Generate). In every state except 'ready' the UI shows the rule template."""
    if not limits.is_enabled(NAME):
        return 'off'
    if is_current(a):
        return 'ready'
    if a.ai_error:
        return 'error'
    return 'stale' if a.ai_text else 'none'
