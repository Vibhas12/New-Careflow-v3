"""Shared agent layer (multi-agent phase 1): kill switch, limits, 429 cooldown, privacy block, output withholding,
run log, provider fallback. No network – the provider is faked."""
from datetime import date
from types import SimpleNamespace

import pytest
from google.genai import errors
from sqlalchemy import delete, select

from app.agents import llm, orchestrator
from app.agents.llm import LLMUnavailable
from app.agents.privacy import deidentify, find_leaks
from app.core.config import get_settings
from app.db import SessionLocal
from app.models import AgentRun, CareGapAlert, Patient, User
from app.services import recommendation_agent as agent

REC = agent.Recommendation(recommendation='Call the patient to rebook the missed appointment.', rationale='The appointment was missed.',
                           task_title='Call patient to rebook')


@pytest.fixture
def on(fake_llm):
    return fake_llm.respond(agent.Recommendation, REC)


@pytest.fixture(autouse=True)
def _no_cooldown_leftovers():
    yield                                                    # a recorded 429 would pause every later test for a minute
    with SessionLocal() as db:
        db.execute(delete(AgentRun).where(AgentRun.error_code == 429))
        db.commit()


def open_alert_id(client) -> str:
    return next(a['id'] for a in client.get('/api/care-gaps').json() if a['status'] == 'Open')


def last_run() -> AgentRun:
    with SessionLocal() as db:
        r = db.execute(select(AgentRun).order_by(AgentRun.id.desc())).scalars().first()
        db.expunge(r)
        return r


# ---------------------------------------------------------------- kill switch (rollback level L1)
def test_kill_switch_all_agents(coord, on, monkeypatch):
    aid = open_alert_id(coord)
    assert coord.post(f'/api/care-gaps/{aid}/recommendation').status_code == 200
    monkeypatch.setattr(get_settings(), 'agents_enabled', False)
    a = next(x for x in coord.get('/api/care-gaps').json() if x['id'] == aid)
    assert a['aiStatus'] == 'off' and a['aiText'] is None                   # stored AI wording hidden as well
    r = coord.post(f'/api/care-gaps/{aid}/recommendation')
    assert r.status_code == 503 and 'switched off' in r.json()['detail']
    assert len(on.calls) == 1 and last_run().status == 'disabled'
    assert coord.get('/api/agents').json()['enabled'] is False


def test_switch_single_agent(coord, on, monkeypatch):
    monkeypatch.setattr(get_settings(), 'agents_disabled', ['recommendation'])
    r = coord.post(f'/api/care-gaps/{open_alert_id(coord)}/recommendation')
    assert r.status_code == 503 and 'recommendation' in r.json()['detail'] and on.calls == []
    st = coord.get('/api/agents').json()
    assert st['enabled'] is True and st['agents'][0] == {'name': 'recommendation', 'label': 'Care-gap recommendation wording',
                                                         'enabled': False, 'reason': st['agents'][0]['reason']}


# ---------------------------------------------------------------- limits
def test_hourly_cap(coord, on, monkeypatch):
    used = coord.get('/api/agents').json()['usage']['usedThisHour']
    monkeypatch.setattr(get_settings(), 'agent_calls_per_user_per_hour', used + 1)
    aid = open_alert_id(coord)
    assert coord.post(f'/api/care-gaps/{aid}/recommendation').status_code == 200
    r = coord.post(f'/api/care-gaps/{aid}/recommendation')
    assert r.status_code == 429 and 'limit' in r.json()['detail'] and r.headers['Retry-After']
    assert len(on.calls) == 1 and last_run().status == 'limited'
    assert coord.get('/api/agents').json()['usage']['remaining'] == 0


def test_cooldown_after_429_on_every_model(coord, doctor, on, monkeypatch):
    on.fail(LLMUnavailable('Gemini API error 429 on every model', 429))
    aid = open_alert_id(coord)
    assert coord.post(f'/api/care-gaps/{aid}/recommendation').status_code == 502
    on.fail(None)
    r = coord.post(f'/api/care-gaps/{aid}/recommendation')
    assert r.status_code == 429 and 'rate-limited' in r.json()['detail'] and int(r.headers['Retry-After']) > 0
    d = doctor.post(f"/api/care-gaps/{open_alert_id(doctor)}/recommendation")    # the key's quota is shared → everyone waits
    assert d.status_code == 429
    assert len(on.calls) == 1
    monkeypatch.setattr(get_settings(), 'agent_cooldown_seconds', 0)
    assert coord.post(f'/api/care-gaps/{aid}/recommendation').status_code == 200


# ---------------------------------------------------------------- privacy and output checks
def test_identifiers_in_input_block_the_call(on):
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.role == 'coordinator')).scalars().first()
        a = db.execute(select(CareGapAlert)).scalars().first()
        p = db.get(Patient, a.patient_id)
        res = orchestrator.run(db, user, 'recommendation', {'reason': f'Call {p.first_name} {p.last_name} ({p.id})'}, patient=p, entity=a.id)
        db.commit()
    assert res.ok is False and res.status == 'blocked' and 'patient ID' in res.issues and on.calls == []
    assert last_run().status == 'blocked'


def test_identifier_in_output_is_withheld(coord, on):
    with SessionLocal() as db:
        aid = open_alert_id(coord)
        pid = db.get(CareGapAlert, aid).patient_id
    on.respond(agent.Recommendation, REC.model_copy(update={'recommendation': f'Call {pid} today.'}))
    r = coord.post(f'/api/care-gaps/{aid}/recommendation')
    assert r.status_code == 502 and 'withheld' in r.json()['detail']
    a = next(x for x in coord.get('/api/care-gaps').json() if x['id'] == aid)
    assert pid not in (a['aiText'] or '')                                   # the withheld text is never shown or stored
    with SessionLocal() as db:
        assert pid not in (db.get(CareGapAlert, aid).ai_text or '')
    run = last_run()
    assert run.status == 'withheld' and run.issues == ['output contains patient ID'] and run.model == 'fake-llm'


def test_empty_output_is_withheld(coord, on):
    on.respond(agent.Recommendation, REC.model_copy(update={'task_title': '  '}))
    assert coord.post(f'/api/care-gaps/{open_alert_id(coord)}/recommendation').status_code == 502
    assert last_run().status == 'withheld'


def test_find_leaks_and_deidentify():
    p = SimpleNamespace(first_name='Sarah', last_name='Thompson', full_name='Sarah Thompson', id='PT-3001', ec_name='John Thompson',
                        dob=date(1980, 3, 7), address='12 Rose Lane, Leeds LS1 2AB')
    assert find_leaks('Due 2026-11-21, review 6 Nov 2026, HbA1c 48 mmol/mol') == []          # dates and values are not phones
    assert find_leaks('ring 07700 900123') == ['phone number']
    assert find_leaks('mail sarah.t@example.com') == ['email address']
    assert find_leaks('PT-3001 missed') == ['patient ID']
    assert set(find_leaks('Sarah, born 07/03/1980, 12 Rose Lane, Leeds LS1 2AB', p)) == {'patient or contact name', 'date of birth', 'address'}
    assert deidentify('Book Sarah Thompson (PT-3001)', p) == 'Book the patient (the patient)'
    assert find_leaks(deidentify('Book Sarah Thompson (PT-3001)', p), p) == []


# ---------------------------------------------------------------- run log
def test_run_log_scoping(coord, admin, on):
    coord.post(f'/api/care-gaps/{open_alert_id(coord)}/recommendation')
    mine = coord.get('/api/agents/runs').json()
    assert mine and all(r['user'] == 'Priya Nair' for r in mine) and mine[0]['patientId']
    assert not {'prompt', 'output', 'text'} & set(mine[0])                  # no content is ever stored or returned
    every = admin.get('/api/agents/runs').json()
    assert every and all(r['patientId'] is None and r['entity'] is None for r in every)
    assert admin.get('/api/agents').json()['usage'] is None


# ---------------------------------------------------------------- provider fallback (llm.generate with a fake SDK client)
class FakeModels:
    def __init__(self, plan):
        self.plan, self.tried = plan, []

    def generate_content(self, *, model, contents, config):
        self.tried.append(model)
        step = self.plan.pop(0)
        if isinstance(step, Exception):
            raise step
        return SimpleNamespace(parsed=step, text=step.model_dump_json())


def fake_client(monkeypatch, plan):
    from google.genai import types
    models = FakeModels(plan)
    monkeypatch.setattr(llm, '_client', lambda: (SimpleNamespace(models=models), types))
    s = get_settings()
    monkeypatch.setattr(s, 'gemini_model', 'm1')
    monkeypatch.setattr(s, 'gemini_fallback_models', ['m2', 'm3'])
    return models


def api_error(code):
    return errors.APIError(code, {'error': {'message': f'error {code}', 'status': 'X'}})


def gen():
    return llm.generate(system='s', prompt='p', schema=agent.Recommendation)


def test_fallback_to_next_model(monkeypatch):
    m = fake_client(monkeypatch, [api_error(503), REC])
    res = gen()
    assert res.model == 'm2' and m.tried == ['m1', 'm2'] and res.attempts == [{'model': 'm1', 'outcome': 'error 503'}, {'model': 'm2', 'outcome': 'ok'}]


def test_quota_on_every_model_reports_429(monkeypatch):
    fake_client(monkeypatch, [api_error(429), api_error(429), api_error(429)])
    with pytest.raises(LLMUnavailable) as e:
        gen()
    assert e.value.code == 429 and len(e.value.attempts) == 3


def test_configuration_error_stops_immediately(monkeypatch):
    m = fake_client(monkeypatch, [api_error(401), REC])
    with pytest.raises(LLMUnavailable) as e:
        gen()
    assert e.value.code == 401 and m.tried == ['m1']
