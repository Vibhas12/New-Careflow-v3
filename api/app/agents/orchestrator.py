"""Runs one agent for one person's request – the only way any code reaches the LLM.

Order of steps (each one timed and recorded in agent_runs.steps – never with prompt or output text):
  0. caller steps – e.g. Context agent / routing / document scrub, measured by the calling service (code, no LLM)
  1. switch      – agent / all agents off, or no key            → 'disabled' and AgentDisabled (HTTP 503); nothing sent
  2. limits      – 429 cooldown or the user's hourly cap         → 'limited'  and AgentLimited  (HTTP 429); nothing sent
  3. privacy in  – identifiers found in the de-identified input  → 'blocked'  result; nothing sent
  4. provider    – one structured request (with model fallback)  → 'failed' result on error (no automatic retry)
  5. verify      – agent.verify() + identifiers in the output    → 'withheld' result; output discarded
  6. success     → 'ok' result with the validated output; the next step is always a person (approve / apply / read)
The caller (a service) decides what to store and commits; on 'failed' / 'blocked' / 'withheld' it keeps the rule template.
Transactions: run() commits the caller's pending work just before the provider request, so no transaction is open while
waiting for the model; callers must not rely on rolling back changes made before run().
There is no chaining: one run() is at most one provider request sequence, and nothing here triggers another run.
Step details are counts and outcomes only (no patient data), so administrators can see the pipeline trace.
"""
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents import base, limits, llm
from app.agents.privacy import find_leaks, find_leaks_many
from app.models import AgentRun, Patient, User
from app.services.common import utcnow

log = logging.getLogger('careflow.agents')
WITHHELD = 'AI output withheld by safety check'          # prefix of the error stored when verify() rejects an output


@dataclass
class AgentResult:
    ok: bool
    status: str                                   # ok | failed | blocked | withheld
    output: BaseModel | None = None
    model: str | None = None
    error: str | None = None
    issues: list[str] = field(default_factory=list)
    run_id: int | None = None


class Steps:
    """Timed pipeline steps: [{name, kind: code|llm, status, ms, detail}]. Details hold counts / outcomes only."""

    def __init__(self, pre: list[dict] | None = None):
        self.items: list[dict] = [dict(s) for s in (pre or [])]
        self._t = time.perf_counter()

    def add(self, name: str, kind: str, status: str, detail: str = '') -> None:
        now = time.perf_counter()
        self.items.append({'name': name, 'kind': kind, 'status': status, 'ms': round((now - self._t) * 1000, 1), 'detail': detail[:200]})
        self._t = now

    def skip(self, *names: str) -> None:
        for n in names:
            self.items.append({'name': n, 'kind': 'llm' if n.startswith('LLM') else 'code', 'status': 'skipped', 'ms': None, 'detail': ''})


def timed_step(name: str, t_start: float, detail: str = '', kind: str = 'code') -> dict:
    """Helper for callers: a finished code step measured from `t_start` (time.perf_counter())."""
    return {'name': name, 'kind': kind, 'status': 'ok', 'ms': round((time.perf_counter() - t_start) * 1000, 1), 'detail': detail[:200]}


def _record(db: Session, *, agent: str, user: User | None, patient: Patient | None, entity: str | None, status: str, t0: float,
            steps: Steps, input_hash: str | None = None, model: str | None = None, attempts: list | None = None, error: str | None = None,
            error_code: int | None = None, issues: list | None = None) -> AgentRun:
    run = AgentRun(created_at=utcnow(), agent=agent, user_id=user.id if user else None, patient_id=patient.id if patient else None,
                   entity=entity, status=status, model=model, attempts=attempts, error=(error or None) and error[:500], error_code=error_code,
                   issues=issues or None, input_hash=input_hash, duration_ms=int((time.monotonic() - t0) * 1000), steps=steps.items)
    db.add(run)
    db.flush()
    return run


LATER = ('Limits', 'Privacy check', 'LLM call', 'Verifier')


def run(db: Session, user: User, agent_name: str, context: dict, *, patient: Patient | None = None, entity: str | None = None,
        patients: list[Patient] | None = None, pre_steps: list[dict] | None = None) -> AgentResult:
    """`patient` – the one patient the request is about (strict leak checks: names, DOB, address, contacts).
    `patients` – several patients (a worklist question): leak checks for each one's full name, ID, DOB and contacts.
    `pre_steps` – code steps the caller already ran and timed (see timed_step), shown first in the pipeline trace."""
    a = base.get(agent_name)
    t0 = time.monotonic()
    st = Steps(pre_steps)
    rec = lambda status, **kw: _record(db, agent=a.name, user=user, patient=patient, entity=entity, status=status, t0=t0, steps=st, **kw)
    leaks_in = (lambda text: find_leaks_many(text, patients)) if patients else (lambda text: find_leaks(text, patient))

    reason = limits.unavailable_reason(a.name)                                   # 1. switch
    if reason:
        st.add('Switch', 'code', 'disabled', reason)
        st.skip(*LATER)
        rec('disabled', error=reason)
        db.commit()
        raise limits.AgentDisabled(reason)
    st.add('Switch', 'code', 'ok', 'agent switched on')
    try:                                                                         # 2. limits
        limits.check(db, user)
    except limits.AgentLimited as e:
        st.add('Limits', 'code', 'limited', e.message)
        st.skip(*LATER[1:])
        rec('limited', error=e.message)
        db.commit()
        raise
    st.add('Limits', 'code', 'ok', 'within the hourly cap, no provider cooldown')

    prompt = a.prompt(context)
    h = hashlib.sha256(prompt.encode()).hexdigest()
    leaks = leaks_in(json.dumps(context, ensure_ascii=False))                    # 3. privacy (input)
    if leaks:
        msg = 'Not sent to the AI: the input still contained ' + ', '.join(leaks)
        log.warning('Agent %s blocked for %s: %s', a.name, entity, leaks)
        st.add('Privacy check', 'code', 'blocked', 'identifiers found: ' + ', '.join(leaks))
        st.skip(*LATER[2:])
        r = rec('blocked', input_hash=h, error=msg, issues=leaks)
        return AgentResult(False, 'blocked', error=msg, issues=leaks, run_id=r.id)
    st.add('Privacy check', 'code', 'ok', f'no identifiers in {len(prompt):,} characters of de-identified input')

    # Never hold a database transaction open while waiting for the network: a slow model call would keep SQLite's
    # read snapshot (or a PostgreSQL "idle in transaction") alive, and the next write could fail with "database is locked".
    db.commit()
    try:                                                                         # 4. provider
        res = llm.generate(system=a.system, prompt=prompt, schema=a.output, temperature=a.temperature, max_output_tokens=a.max_output_tokens)
    except llm.LLMUnavailable as e:
        log.warning('Agent %s failed for %s: %s', a.name, entity, e)
        st.add('LLM call', 'llm', 'failed', ' → '.join(f"{x['model']}: {x['outcome']}" for x in e.attempts) or str(e)[:160])
        st.skip('Verifier')
        r = rec('failed', input_hash=h, attempts=e.attempts, error=str(e), error_code=e.code)
        return AgentResult(False, 'failed', error=str(e), run_id=r.id)
    st.add('LLM call', 'llm', 'ok', ' → '.join(f"{x['model']}: {x['outcome']}" for x in res.attempts) or res.model)

    out = a.clean(res.output, context)                                           # 5. verify
    issues = list(a.verify(out, context))
    issues += [f'output contains {k}' for k in leaks_in(out.model_dump_json())]
    if issues:
        msg = f'{WITHHELD}: ' + '; '.join(issues)
        log.warning('Agent %s output withheld for %s: %s', a.name, entity, issues)
        st.add('Verifier', 'code', 'withheld', f'{len(issues)} problem(s): ' + '; '.join(issues))
        r = rec('withheld', input_hash=h, model=res.model, attempts=res.attempts, error=msg, issues=issues)
        return AgentResult(False, 'withheld', model=res.model, error=msg, issues=issues, run_id=r.id)
    st.add('Verifier', 'code', 'ok', 'all checks passed')

    r = rec('ok', input_hash=h, model=res.model, attempts=res.attempts)          # 6. success
    return AgentResult(True, 'ok', output=out, model=res.model, run_id=r.id)
