"""Care-gap recommendation agent – words the 'Recommended next action' for an alert with Google Gemini.

Division of labour (unchanged safety model):
  * the deterministic rule engine (services/care_gaps.py) decides THAT there is a gap, its priority and its evidence;
  * this agent only WORDS the next coordination step, a one-line rationale and a task title;
  * a person still approves, modifies or dismisses – nothing is executed by the model.

Data minimisation: the model receives de-identified facts only – category, rule, priority, reason, evidence text,
department, primary condition and the rule's template action. No names, IDs, dates of birth or contact details are sent
(patient names and IDs that appear inside rule text are replaced before sending).

Without a configured key (CAREFLOW_GEMINI_API_KEY) or when the call fails, the UI keeps showing the rule template.
"""
import hashlib
import json
import logging
import re

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import CareGapAlert, Patient
from app.services.care_gaps import RULES
from app.services.common import utcnow

log = logging.getLogger('careflow.llm')

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


class LLMUnavailable(Exception):
    pass


def source_hash(a: CareGapAlert) -> str:
    """Fingerprint of the facts the wording depends on – a change re-triggers wording."""
    facts = json.dumps([a.rule, a.priority, a.reason, [e.get('text') for e in a.evidence or []], a.action.get('title')], sort_keys=True)
    return hashlib.sha256(facts.encode()).hexdigest()


def is_current(a: CareGapAlert) -> bool:
    return bool(a.ai_text) and a.ai_source_hash == source_hash(a)


def _deidentify(text: str, p: Patient | None) -> str:
    if not text:
        return text
    if p:
        for s in {p.full_name, p.first_name, p.last_name}:
            if s and len(s) > 1:
                text = re.sub(re.escape(s), 'the patient', text, flags=re.I)
    return re.sub(r'\bPT-\d{3,6}\b', 'the patient', text)


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


def _client():
    cfg = get_settings()
    if not cfg.llm_configured:
        raise LLMUnavailable('No Gemini API key configured (CAREFLOW_GEMINI_API_KEY)')
    from google import genai
    from google.genai import types
    # one attempt per model (fail fast) – call_llm moves on to the next model instead of the SDK retrying the busy one
    opts = types.HttpOptions(timeout=cfg.llm_timeout_seconds * 1000, retry_options=types.HttpRetryOptions(attempts=1))
    return genai.Client(api_key=cfg.gemini_api_key, http_options=opts), types


def call_llm(context: dict) -> tuple[Recommendation, str]:
    """One structured Gemini call. Returns (validated recommendation, model id)."""
    from google.genai import errors
    client, types = _client()
    cfg = get_settings()
    resp, model, last = None, None, None
    for model in [cfg.gemini_model, *cfg.gemini_fallback_models]:
        try:
            resp = client.models.generate_content(
                model=model,
                contents='Word the recommended next action for this care gap. Facts (JSON):\n' + json.dumps(context, ensure_ascii=False),
                config=types.GenerateContentConfig(system_instruction=SYSTEM, response_mime_type='application/json', response_schema=Recommendation,
                                                   temperature=0.2, max_output_tokens=2048))
            break
        except errors.APIError as e:
            last = LLMUnavailable(f'Gemini API error {getattr(e, "code", "")} on {model}: {getattr(e, "message", None) or str(e)[:160]}')
            if getattr(e, 'code', None) in (404, 429, 500, 503, 504):
                log.info('Gemini %s unavailable (%s) – trying the next model', model, getattr(e, 'code', ''))
                continue                         # overloaded / rate-limited / not enabled for this key → next model
            raise last from e                    # 400 / 401 / 403: a configuration problem – retrying another model won't help
        except Exception as e:                   # network error / read timeout → try the next model as well
            last = LLMUnavailable(f'Gemini call failed on {model}: {type(e).__name__}: {str(e)[:160]}')
            log.info('Gemini %s failed (%s) – trying the next model', model, type(e).__name__)
    if resp is None:
        raise last or LLMUnavailable('No Gemini model available')
    rec = resp.parsed if isinstance(resp.parsed, Recommendation) else None
    if rec is None:
        try:
            rec = Recommendation.model_validate_json(resp.text or '')
        except ValidationError as e:
            raise LLMUnavailable('Gemini returned an unexpected format') from e
    rec.recommendation, rec.rationale, rec.task_title = (s.strip() for s in (rec.recommendation, rec.rationale, rec.task_title))
    if not rec.recommendation or not rec.task_title:
        raise LLMUnavailable('Gemini returned an empty recommendation')
    rec.task_title = rec.task_title[:80]
    rec.recommendation, rec.rationale = rec.recommendation[:600], rec.rationale[:400]
    return rec, model


def word(db: Session, a: CareGapAlert, *, commit: bool = True) -> bool:
    """Word one alert. Stores the result (or the error) on the alert; never raises for LLM problems."""
    p = db.get(Patient, a.patient_id)
    h = source_hash(a)
    try:
        rec, model = call_llm(build_context(a, p))
    except LLMUnavailable as e:
        a.ai_error = str(e)[:500]
        log.warning('Recommendation wording failed for %s: %s', a.id, e)
        if commit:
            db.commit()
        return False
    a.ai_text, a.ai_rationale, a.ai_task_title = rec.recommendation, rec.rationale, rec.task_title
    a.ai_model, a.ai_generated_at, a.ai_source_hash, a.ai_error = model, utcnow(), h, None
    if commit:
        db.commit()
    return True


def status(a: CareGapAlert) -> str:
    """'ready' – wording matches the current facts · 'off' – no key configured · 'error' – the last attempt failed
    (the rule template is shown) · 'pending' – queued for the background agent run."""
    if is_current(a):
        return 'ready'
    if not get_settings().llm_configured:
        return 'off'
    return 'error' if a.ai_error else 'pending'
