"""Runs one agent for one person's request – the only way any code reaches the LLM.

Order of steps (each one recorded in agent_runs, never with prompt or output text):
  1. switch      – agent / all agents off, or no key            → 'disabled' and AgentDisabled (HTTP 503); nothing sent
  2. limits      – 429 cooldown or the user's hourly cap         → 'limited'  and AgentLimited  (HTTP 429); nothing sent
  3. privacy in  – identifiers found in the de-identified input  → 'blocked'  result; nothing sent
  4. provider    – one structured request (with model fallback)  → 'failed' result on error (no automatic retry)
  5. verify      – agent.verify() + identifiers in the output    → 'withheld' result; output discarded
  6. success     → 'ok' result with the validated output
The caller (a service) decides what to store and commits; on 'failed' / 'blocked' / 'withheld' it keeps the rule template.
There is no chaining: one run() is at most one provider request sequence, and nothing here triggers another run.
"""
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents import base, limits, llm
from app.agents.privacy import find_leaks
from app.models import AgentRun, Patient, User
from app.services.common import utcnow

log = logging.getLogger('careflow.agents')


@dataclass
class AgentResult:
    ok: bool
    status: str                                   # ok | failed | blocked | withheld
    output: BaseModel | None = None
    model: str | None = None
    error: str | None = None
    issues: list[str] = field(default_factory=list)
    run_id: int | None = None


def _record(db: Session, *, agent: str, user: User | None, patient: Patient | None, entity: str | None, status: str, t0: float,
            input_hash: str | None = None, model: str | None = None, attempts: list | None = None, error: str | None = None,
            error_code: int | None = None, issues: list | None = None) -> AgentRun:
    run = AgentRun(created_at=utcnow(), agent=agent, user_id=user.id if user else None, patient_id=patient.id if patient else None,
                   entity=entity, status=status, model=model, attempts=attempts, error=(error or None) and error[:500], error_code=error_code,
                   issues=issues or None, input_hash=input_hash, duration_ms=int((time.monotonic() - t0) * 1000))
    db.add(run)
    db.flush()
    return run


def run(db: Session, user: User, agent_name: str, context: dict, *, patient: Patient | None = None, entity: str | None = None) -> AgentResult:
    a = base.get(agent_name)
    t0 = time.monotonic()
    rec = lambda status, **kw: _record(db, agent=a.name, user=user, patient=patient, entity=entity, status=status, t0=t0, **kw)

    reason = limits.unavailable_reason(a.name)                                   # 1. switch
    if reason:
        rec('disabled', error=reason)
        db.commit()
        raise limits.AgentDisabled(reason)
    try:                                                                         # 2. limits
        limits.check(db, user)
    except limits.AgentLimited as e:
        rec('limited', error=e.message)
        db.commit()
        raise

    prompt = a.prompt(context)
    h = hashlib.sha256(prompt.encode()).hexdigest()
    leaks = find_leaks(json.dumps(context, ensure_ascii=False), patient)        # 3. privacy (input)
    if leaks:
        msg = 'Not sent to the AI: the input still contained ' + ', '.join(leaks)
        log.warning('Agent %s blocked for %s: %s', a.name, entity, leaks)
        r = rec('blocked', input_hash=h, error=msg, issues=leaks)
        return AgentResult(False, 'blocked', error=msg, issues=leaks, run_id=r.id)

    try:                                                                         # 4. provider
        res = llm.generate(system=a.system, prompt=prompt, schema=a.output, temperature=a.temperature, max_output_tokens=a.max_output_tokens)
    except llm.LLMUnavailable as e:
        log.warning('Agent %s failed for %s: %s', a.name, entity, e)
        r = rec('failed', input_hash=h, attempts=e.attempts, error=str(e), error_code=e.code)
        return AgentResult(False, 'failed', error=str(e), run_id=r.id)

    out = a.clean(res.output)                                                    # 5. verify
    issues = list(a.verify(out, context))
    issues += [f'output contains {k}' for k in find_leaks(out.model_dump_json(), patient)]
    if issues:
        msg = 'AI output withheld by safety check: ' + '; '.join(issues)
        log.warning('Agent %s output withheld for %s: %s', a.name, entity, issues)
        r = rec('withheld', input_hash=h, model=res.model, attempts=res.attempts, error=msg, issues=issues)
        return AgentResult(False, 'withheld', model=res.model, error=msg, issues=issues, run_id=r.id)

    r = rec('ok', input_hash=h, model=res.model, attempts=res.attempts)          # 6. success
    return AgentResult(True, 'ok', output=out, model=res.model, run_id=r.id)
