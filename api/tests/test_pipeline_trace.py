"""v3.7: timed pipeline steps on every agent run, and the administrator's Settings → AI agent pipeline view (no patient references)."""
import json

import pytest
from sqlalchemy import select

from app.agents.llm import LLMUnavailable
from app.core.config import get_settings
from app.db import SessionLocal
from app.models import AgentRun
from app.services import recommendation_agent as ra
from app.services import summary_agent as sa

ORCH = ['Switch', 'Limits', 'Privacy check', 'LLM call', 'Verifier']


def last_steps():
    with SessionLocal() as db:
        r = db.execute(select(AgentRun).order_by(AgentRun.id.desc())).scalars().first()
        return r.agent, r.status, r.steps


def faithful(prompt):
    ctx = json.loads(prompt.split('Facts (JSON):\n', 1)[1])
    parts = {s: [sa.Statement(text=f['text'], kind=f['kind'], sources=f['sources']) for f in ctx['facts'] if f['section'] == s] for s in sa.SECTIONS}
    return sa.PatientSummary(overview=(parts['gaps'] or parts['context'])[:1], **parts)


@pytest.fixture
def pid(coord):
    return next(a['patientId'] for a in coord.get('/api/care-gaps').json() if a['status'] == 'Open')


def test_successful_run_records_every_step_with_timings(coord, fake_llm, pid):
    fake_llm.respond(sa.PatientSummary, faithful)
    assert coord.post(f'/api/assistant/patients/{pid}/summary/ai').status_code == 200
    agent, status, steps = last_steps()
    assert agent == 'summary' and status == 'ok'
    assert [s['name'] for s in steps] == ['Context agent', *ORCH]
    assert all(s['status'] == 'ok' and isinstance(s['ms'], float) for s in steps)
    assert [s['kind'] for s in steps] == ['code', 'code', 'code', 'code', 'llm', 'code']
    assert 'fake-llm: ok' in steps[4]['detail'] and 'de-identified fact' in steps[0]['detail']
    assert pid not in json.dumps(steps)                                              # counts and outcomes only


def test_withheld_failed_and_disabled_runs_show_where_they_stopped(coord, fake_llm, pid, monkeypatch):
    fake_llm.respond(sa.PatientSummary, lambda p: faithful(p).model_copy(update={'gaps': []}))
    coord.post(f'/api/assistant/patients/{pid}/summary/ai')
    _, status, steps = last_steps()
    assert status == 'withheld' and steps[-1]['name'] == 'Verifier' and steps[-1]['status'] == 'withheld' and 'drops a care gap' in steps[-1]['detail']

    fake_llm.fail(LLMUnavailable('Gemini API error 503 on m1', 503, [{'model': 'm1', 'outcome': 'error 503'}, {'model': 'm2', 'outcome': 'error 503'}]))
    coord.post(f'/api/assistant/patients/{pid}/summary/ai')
    _, status, steps = last_steps()
    llm = next(s for s in steps if s['name'] == 'LLM call')
    assert status == 'failed' and llm['status'] == 'failed' and llm['detail'] == 'm1: error 503 → m2: error 503'
    assert steps[-1] == {'name': 'Verifier', 'kind': 'code', 'status': 'skipped', 'ms': None, 'detail': ''}

    monkeypatch.setattr(get_settings(), 'agents_disabled', ['summary'])
    coord.post(f'/api/assistant/patients/{pid}/summary/ai')
    _, status, steps = last_steps()
    assert status == 'disabled' and steps[1]['status'] == 'disabled' and {s['status'] for s in steps[2:]} == {'skipped'}


def test_recommendation_run_has_its_context_step(coord, fake_llm):
    fake_llm.respond(ra.Recommendation, ra.Recommendation(recommendation='Contact the patient to rebook.', rationale='Missed.', task_title='Rebook'))
    aid = next(a['id'] for a in coord.get('/api/care-gaps').json() if a['status'] == 'Open')
    coord.post(f'/api/care-gaps/{aid}/recommendation')
    agent, _, steps = last_steps()
    assert agent == 'recommendation' and steps[0]['name'] == 'Context (alert facts, de-identified)' and 'evidence item' in steps[0]['detail']


# ---------------------------------------------------------------- Settings → AI agent pipeline (administrators)
def test_pipeline_view_is_admin_only(coord, doctor):
    assert coord.get('/api/agents/pipeline').status_code == 403
    assert doctor.get('/api/agents/pipeline').status_code == 403


def test_pipeline_view_aggregates_without_patient_references(admin, coord, fake_llm, pid):
    fake_llm.respond(sa.PatientSummary, faithful)
    coord.post(f'/api/assistant/patients/{pid}/summary/ai')
    d = admin.get('/api/agents/pipeline?range=all').json()
    blob = json.dumps(d)
    assert 'PT-' not in blob and '"patientId"' not in blob and '"entity"' not in blob
    k = d['kpis']
    assert k['runs'] >= k['aiCalls'] >= k['accepted'] >= 1 and k['autonomousActions'] == 0 and d['onDemandOnly'] is True
    assert {a['name'] for a in d['agents']} == {'recommendation', 'summary', 'answer', 'import_extract', 'import_map', 'insights', 'reviewer'}
    assert all(a['humanStep'] for a in d['agents'])
    run = next(r for r in d['runs'] if r['agent'] == 'summary' and r['status'] == 'ok')
    assert [s['name'] for s in run['steps']] == ['Context agent', *ORCH] and run['user'] == 'Priya Nair'
    assert set(d['byDay']['series']) == {'Accepted', 'Withheld', 'Failed', 'Not sent'} and len(d['byDay']['labels']) == 14
    assert set(d['jobs']) <= {'deliver_reminders', 'scan_care_gaps'}
