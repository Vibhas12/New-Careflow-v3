"""Context agent + patient summary agent (multi-agent phase 3) – fake LLM, no network."""
import json

import pytest
from sqlalchemy import select

from app.agents.context import patient_context
from app.agents.privacy import find_leaks
from app.core.config import get_settings
from app.db import SessionLocal
from app.models import AgentRun, AiSummary, Patient, User
from app.services import summary_agent as sa


def facts_from(prompt: str) -> dict:
    return json.loads(prompt.split('Facts (JSON):\n', 1)[1])


def faithful(prompt: str) -> sa.PatientSummary:
    """A well-behaved model: restates every fact in its section and picks an overview."""
    ctx = facts_from(prompt)
    parts = {s: [sa.Statement(text=f['text'], kind=f['kind'], sources=f['sources']) for f in ctx['facts'] if f['section'] == s] for s in sa.SECTIONS}
    overview = (parts['gaps'] or parts['context'])[:1]
    return sa.PatientSummary(overview=overview, **parts)


@pytest.fixture
def llm(fake_llm):
    return fake_llm.respond(sa.PatientSummary, faithful)


@pytest.fixture
def pid(coord):
    return next(a['patientId'] for a in coord.get('/api/care-gaps').json() if a['status'] == 'Open')


def clear(pid):
    with SessionLocal() as db:
        row = db.get(AiSummary, pid)
        if row:
            db.delete(row)
            db.commit()


# ---------------------------------------------------------------- Context agent
def test_context_is_scoped_numbered_and_deidentified(pid):
    with SessionLocal() as db:
        coord = db.execute(select(User).where(User.role == 'coordinator')).scalars().first()
        ctx = patient_context(db, coord, pid)
        p = db.get(Patient, pid)
        staff = [n for (n,) in db.execute(select(User.name)).all()]
        blob = json.dumps(ctx.llm)
        assert find_leaks(blob, p) == []                                          # no names, IDs, contacts, DOB, address
        assert p.first_name not in blob and p.last_name not in blob and pid not in blob
        assert not [n for n in staff if n in blob]                                # staff names replaced by their role
        assert {s['n'] for s in ctx.llm['sources']} == {e['n'] for e in ctx.brief['evidence']}
        assert all(set(s) == {'n', 'label'} for s in ctx.llm['sources'])         # labels only – no record IDs
        assert {f['section'] for f in ctx.llm['facts']} <= set(sa.SECTIONS)       # next steps stay rule-based
        assert patient_context(db, coord, pid).fingerprint == ctx.fingerprint     # stable for unchanged records


def test_scope_doctor_and_admin(doctor, admin, coord, llm):
    with SessionLocal() as db:
        me = db.execute(select(User).where(User.email == 'sarah.wilson@careflow.demo')).scalars().one()
        other = db.execute(select(Patient).where(Patient.doctor_id != me.id)).scalars().first()
    assert doctor.post(f'/api/assistant/patients/{other.id}/summary/ai').status_code == 404
    assert admin.post(f'/api/assistant/patients/{other.id}/summary/ai').status_code == 403
    assert llm.calls == []


# ---------------------------------------------------------------- on demand, stored, stale
def test_get_never_calls_the_model(coord, pid, llm):
    clear(pid)
    b = coord.get(f'/api/assistant/patients/{pid}/summary').json()
    assert b['ai'] == {'status': 'none'} and b['sections']['gaps'] and llm.calls == []


def test_off_without_key(coord, pid):
    b = coord.get(f'/api/assistant/patients/{pid}/summary').json()
    assert b['ai']['status'] == 'off'
    assert coord.post(f'/api/assistant/patients/{pid}/summary/ai').status_code == 503


def test_generate_store_and_reuse(coord, pid, llm):
    clear(pid)
    r = coord.post(f'/api/assistant/patients/{pid}/summary/ai')
    assert r.status_code == 200, r.text
    ai = r.json()['ai']
    assert ai['status'] == 'ready' and ai['model'] == 'fake-llm' and 1 <= len(ai['overview']) <= 3 and ai['gaps']
    assert len(llm.calls) == 1 and llm.calls[0]['schema'] == 'PatientSummary'
    again = coord.get(f'/api/assistant/patients/{pid}/summary').json()
    assert again['ai']['status'] == 'ready' and again['ai']['overview'] == ai['overview'] and len(llm.calls) == 1   # reused, no new call
    assert r.json()['sections']['next']                                           # rule-based next steps still there


def test_changed_records_make_it_stale(coord, pid, llm):
    clear(pid)
    coord.post(f'/api/assistant/patients/{pid}/summary/ai')
    with SessionLocal() as db:
        p = db.get(Patient, pid)
        old, p.family_history = p.family_history, (p.family_history or '') + ' (updated)'
        db.commit()
    try:
        assert coord.get(f'/api/assistant/patients/{pid}/summary').json()['ai'] == {'status': 'stale'}
        assert len(llm.calls) == 1                                                # never re-written automatically
    finally:
        with SessionLocal() as db:
            db.get(Patient, pid).family_history = old
            db.commit()


def test_switch_off_summary_only(coord, pid, llm, monkeypatch):
    monkeypatch.setattr(get_settings(), 'agents_disabled', ['summary'])
    assert coord.get(f'/api/assistant/patients/{pid}/summary').json()['ai']['status'] == 'off'
    assert coord.post(f'/api/assistant/patients/{pid}/summary/ai').status_code == 503
    names = {a['name']: a['enabled'] for a in coord.get('/api/agents').json()['agents']}
    assert names['summary'] is False and all(v for k, v in names.items() if k != 'summary')       # only the summary agent is off


# ---------------------------------------------------------------- verifier
def test_faithful_summary_passes_for_every_patient():
    """No false alarms: restating each patient's recorded facts passes all summary checks."""
    agent = sa.SummaryAgent()
    with SessionLocal() as db:
        coord = db.execute(select(User).where(User.role == 'coordinator')).scalars().first()
        ids = [p for (p,) in db.execute(select(Patient.id).where(Patient.discharged.is_(False), Patient.draft.is_(False))).all()]
        for pid in ids:
            ctx = patient_context(db, coord, pid)
            out = agent.clean(faithful(agent.prompt(ctx.llm)))
            assert agent.verify(out, ctx.llm) == [], pid
        db.rollback()
    assert len(ids) >= 10


def bad(prompt, **change):
    s = faithful(prompt)
    for k, v in change.items():
        setattr(s, k, v(s) if callable(v) else v)
    return s


@pytest.mark.parametrize('change, expected', [
    ({'overview': lambda s: [sa.Statement(text='The patient is stable.', kind='fact', sources=[999])]}, 'does not exist'),
    ({'overview': lambda s: [sa.Statement(text='The patient has open care gaps.', kind='fact', sources=[])]}, 'has no source'),
    ({'gaps': []}, 'drops a care gap'),
    ({'overview': lambda s: [sa.Statement(text='Findings are consistent with heart failure.', kind='fact', sources=[1])]}, 'interprets findings'),
    ({'overview': lambda s: [sa.Statement(text='Ask the doctor to increase the dose of the medication.', kind='suggestion', sources=[1])]},
     'medication or treatment change'),
    ({'overview': lambda s: [sa.Statement(text='An MRI is booked for 30 Dec 2031.', kind='fact', sources=[1])]}, 'not in the facts'),
    ({'overview': []}, 'overview must have 1-3'),
])
def test_unsafe_summary_is_withheld(coord, pid, llm, change, expected):
    clear(pid)
    llm.respond(sa.PatientSummary, lambda prompt: bad(prompt, **change))
    r = coord.post(f'/api/assistant/patients/{pid}/summary/ai')
    assert r.status_code == 502 and 'withheld by safety check' in r.json()['detail'] and expected in r.json()['detail']
    b = coord.get(f'/api/assistant/patients/{pid}/summary').json()
    assert b['ai']['status'] == 'withheld' and 'overview' not in b['ai'] and b['sections']['context']   # template stays
    with SessionLocal() as db:
        run = db.execute(select(AgentRun).order_by(AgentRun.id.desc())).scalars().first()
        assert run.agent == 'summary' and run.status == 'withheld' and any(expected in i for i in run.issues)


def test_failed_regenerate_keeps_valid_summary(coord, pid, llm):
    from app.agents.llm import LLMUnavailable
    clear(pid)
    coord.post(f'/api/assistant/patients/{pid}/summary/ai')
    llm.fail(LLMUnavailable('Gemini API error 503: overloaded', 503))
    assert coord.post(f'/api/assistant/patients/{pid}/summary/ai').status_code == 502
    ai = coord.get(f'/api/assistant/patients/{pid}/summary').json()['ai']
    assert ai['status'] == 'ready' and 'overloaded' in ai['lastError'] and ai['overview']
