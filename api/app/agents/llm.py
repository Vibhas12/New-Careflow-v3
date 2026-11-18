"""LLM provider layer (Google Gemini, `google-genai` SDK) shared by every agent.

* One structured-output request per call: the response must validate against the agent's Pydantic schema.
* Fail fast: one SDK attempt per model; on 404 / 429 / 500 / 503 / 504, a timeout or a network error the next model in
  CAREFLOW_GEMINI_FALLBACK_MODELS is tried. 400 / 401 / 403 are configuration problems and stop immediately.
* Never called directly by routes or services – only through agents.orchestrator.run(), which applies the
  on/off switch, limits, privacy checks and the run log first.
"""
import logging
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError

from app.core.config import get_settings

log = logging.getLogger('careflow.llm')
FALLBACK_CODES = (404, 429, 500, 503, 504)


class LLMUnavailable(Exception):
    """The provider could not produce a valid answer. `code` is the HTTP status when known (429 = quota on every model)."""

    def __init__(self, message: str, code: int | None = None, attempts: list[dict] | None = None):
        super().__init__(message)
        self.code, self.attempts = code, attempts or []


@dataclass
class LLMResult:
    output: BaseModel
    model: str
    attempts: list[dict] = field(default_factory=list)       # [{model, outcome}] in the order tried


def _client():
    cfg = get_settings()
    if not cfg.llm_configured:
        raise LLMUnavailable('No Gemini API key configured (CAREFLOW_GEMINI_API_KEY)')
    from google import genai
    from google.genai import types
    # one attempt per model (fail fast) – generate() moves on to the next model instead of the SDK retrying the busy one
    opts = types.HttpOptions(timeout=cfg.llm_timeout_seconds * 1000, retry_options=types.HttpRetryOptions(attempts=1))
    return genai.Client(api_key=cfg.gemini_api_key, http_options=opts), types


def generate(*, system: str, prompt: str, schema: type[BaseModel], temperature: float = 0.2, max_output_tokens: int = 2048) -> LLMResult:
    """One structured request (with model fallback). Returns the validated output or raises LLMUnavailable."""
    from google.genai import errors
    client, types = _client()
    cfg = get_settings()
    attempts: list[dict] = []
    resp, model, last = None, None, None
    for model in [cfg.gemini_model, *cfg.gemini_fallback_models]:
        try:
            resp = client.models.generate_content(
                model=model, contents=prompt,
                config=types.GenerateContentConfig(system_instruction=system, response_mime_type='application/json', response_schema=schema,
                                                   temperature=temperature, max_output_tokens=max_output_tokens))
            attempts.append({'model': model, 'outcome': 'ok'})
            break
        except errors.APIError as e:
            code = getattr(e, 'code', None)
            attempts.append({'model': model, 'outcome': f'error {code}'})
            last = LLMUnavailable(f'Gemini API error {code or ""} on {model}: {getattr(e, "message", None) or str(e)[:160]}', code, attempts)
            if code in FALLBACK_CODES:
                log.info('Gemini %s unavailable (%s) – trying the next model', model, code)
                continue                         # overloaded / rate-limited / not enabled for this key → next model
            raise last from e                    # 400 / 401 / 403: a configuration problem – another model won't help
        except Exception as e:                   # network error / read timeout → try the next model as well
            attempts.append({'model': model, 'outcome': type(e).__name__})
            last = LLMUnavailable(f'Gemini call failed on {model}: {type(e).__name__}: {str(e)[:160]}', None, attempts)
            log.info('Gemini %s failed (%s) – trying the next model', model, type(e).__name__)
    if resp is None:
        if last is not None and attempts and all(x['outcome'] == 'error 429' for x in attempts):
            last.code = 429                      # quota exhausted on every model → the orchestrator starts a cooldown
        raise last or LLMUnavailable('No Gemini model available', None, attempts)
    out = resp.parsed if isinstance(resp.parsed, schema) else None
    if out is None:
        try:
            out = schema.model_validate_json(resp.text or '')
        except ValidationError as e:
            raise LLMUnavailable(f'{model} returned an unexpected format', None, attempts) from e
    return LLMResult(out, model, attempts)
