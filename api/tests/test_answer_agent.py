"""AI Care Assistant "Ask AI" (multi-agent phase 4) – orchestrator routing, worklist de-identification, answer agent,
drafted proposals, verifier and template fallback. Fake LLM, no network."""
import json

import pytest
from sqlalchemy import select

from app.agents.privacy import find_leaks_many
from app.core.config import get_settings
from app.db import SessionLocal
from app.models import AgentRun, AssistantProposal, Patient, User
from app.services import answer_agent as aa
from app.services.assistant import _pool


def facts(prompt: str) -> dict:
    return json.loads(prompt.split('Facts (JSON):\n', 1)[1])


def question(prompt: str) -> str:
    return prompt.split('\n', 1)[0].removeprefix('Question: ')


def good(prompt: str, actions=()) -> aa.Answer:
    """A well-behaved model: answers with the care-gap facts it was given."""
    ctx = facts(prompt)
    gaps = [f for f in ctx['facts'] if f['section'] in ('care gap', 'gaps')][:4] or ctx['facts'][:2]
    st = [aa.AnswerStatement(text=f['text'], kind='fact', sources=f['sources'], patient=f['patient']) for f in gaps]
    return aa.Answer(intro=f'{len(st)} item(s) need attention.', statements=st, actions=list(actions))


@pytest.fixture
def llm(fake_llm):
    return fake_llm.respond(aa.Answer, good)


def user(email):
    with SessionLocal() as db:
        u = db.execute(select(User).where(User.email == email)).scalars().one()
        db.expunge(u)
        return u


def ask(client, text, **kw):
    r = client.post('/api/assistant/messages', json={'text': text, **kw})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- send stays template-only
def test_send_never_calls_the_model(coord, llm):
    m = ask(coord, 'Which patients have overdue follow-ups?')
    assert m['ai'] is False and llm.calls == []


def test_unmatched_template_offers_ai(coord):
    m = ask(coord, 'Tell me something interesting about our week')
    assert m['offerAi'] is True and m['ai'] is False


# ---------------------------------------------------------------- context: scoped and de-identified
def test_worklist_context_is_deidentified_and_scoped():
    with SessionLocal() as db:
        for email in ('priya.nair@careflow.demo', 'sarah.wilson@careflow.demo'):
            u = db.execute(select(User).where(User.email == email)).scalars().one()
            pool = _pool(db, u)
            sc = aa.worklist_scope(db, u, pool)
            q = 'What is pending for Dr. Wilson and ' + pool[0].full_name + ' (' + pool[0].id + ')?'
            blob = json.dumps(sc.llm(q, 'worklist'))
            assert find_leaks_many(blob, pool) == [], email
            assert not [n for (n,) in db.execute(select(User.name)).all() if n in blob]             # staff → aliases / "you"
            assert len(sc.alias) == len(pool) and set(sc.alias.values()) == set(pool)
            assert 'Patient A' in sc.question(q) and pool[0].id not in sc.question(q)
        doctor_pool = _pool(db, db.execute(select(User).where(User.email == 'sarah.wilson@careflow.demo')).scalars().one())
        assert all(p.doctor_id == doctor_pool[0].doctor_id for p in doctor_pool)                   # doctors: own patients only


def test_deidentify_whole_words_only():
    from types import SimpleNamespace
    from app.agents.privacy import deidentify
    p = SimpleNamespace(id='PT-1', first_name='Ann', last_name='Lee', full_name='Ann Lee')
    assert deidentify('Annual review for Ann; Leeds clinic', p, 'Patient A') == 'Annual review for Patient A; Leeds clinic'


# ---------------------------------------------------------------- Ask AI
def test_ask_ai_worklist_answer(coord, llm):
    m = ask(coord, 'Which patients need attention today?', ai=True)
    assert m['ai'] is True and m['model'] == 'fake-llm' and len(llm.calls) == 1
    b = next(x for x in m['blocks'] if x['type'] == 'answer')
    assert b['statements'] and all(s['sources'] for s in b['statements']) and b['evidence']
    assert any(s['patientId'] and f"({s['patientId']})" in s['text'] for s in b['statements'])    # aliases mapped back after checks
    assert not any('Patient A' in s['text'] for s in b['statements'])
    assert any('worklist' in t for t in m['trace']) and any(t.startswith('Verifier: passed') for t in m['trace'])
    assert 'Question: Which patients need attention today?' in llm.calls[0]['prompt']


def test_ask_ai_routes_named_patient(coord, llm):
    with SessionLocal() as db:
        p = db.execute(select(Patient).where(Patient.discharged.is_(False)).order_by(Patient.id)).scalars().first()
        name, pid = p.full_name, p.id
    m = ask(coord, f'What is outstanding for {name}?', ai=True)
    assert m['patientId'] == pid and any('patient context' in t for t in m['trace'])
    ctx = facts(llm.calls[0]['prompt'])
    assert ctx['patients'] == ['Patient A'] and ctx['scope'] == 'patient'
    assert name not in llm.calls[0]['prompt'] and pid not in llm.calls[0]['prompt']
    assert 'Patient A' in question(llm.calls[0]['prompt'])


def test_drafted_actions_become_proposals(coord, llm):
    llm.respond(aa.Answer, lambda prompt: good(prompt, [aa.DraftAction(patient='Patient A', type='task', title='Call Patient A to rebook the review',
                                                                         message='', due_in_days=2),
                                                         aa.DraftAction(patient='Patient A', type='reminder', title='Appointment reminder',
                                                                         message='Please contact your care team to book your next appointment.', due_in_days=1)]))
    m = ask(coord, 'Draft a follow-up for the first patient', ai=True)
    props = next(x for x in m['blocks'] if x['type'] == 'proposals')['proposals']
    assert [p['status'] for p in props] == ['Proposed', 'Proposed'] and 'Patient A' not in props[0]['title']
    with SessionLocal() as db:
        pa = db.get(Patient, props[0]['patientId'])
        assert props[0]['title'] == f'Call {pa.full_name} ({pa.id}) to rebook the review'
    r = coord.post(f"/api/assistant/proposals/{props[0]['id']}/approve").json()
    assert r['status'] == 'Approved' and r['resultRef'].startswith('T')                            # created only on approval


@pytest.mark.parametrize('bad, why', [
    (lambda p: aa.Answer(intro='Patient A likely has worsening diabetes.', statements=[], actions=[]), 'speculates'),
    (lambda p: aa.Answer(intro='Two items.', statements=[aa.AnswerStatement(text='Patient Z is overdue.', kind='fact', sources=[1], patient='Patient Z')],
                         actions=[]), 'unknown patient'),
    (lambda p: aa.Answer(intro='One item.', statements=[aa.AnswerStatement(text='Something happened.', kind='fact', sources=[9999], patient='')],
                         actions=[]), 'does not exist'),
    (lambda p: aa.Answer(intro='Done.', statements=[], actions=[aa.DraftAction(patient='Patient A', type='task', title='Increase the dose of insulin',
                                                                               message='', due_in_days=1)]), 'medication'),
])
def test_unsafe_answer_falls_back_to_template(coord, llm, bad, why):
    before = len(list(SessionLocal().execute(select(AssistantProposal)).scalars()))
    llm.respond(aa.Answer, bad)
    m = ask(coord, 'Which patients have overdue follow-ups?', ai=True)
    assert m['ai'] is False and m['text'].startswith('The AI answer was withheld by the safety check')
    assert any('withheld' in t and why in t for t in m['trace'])
    with SessionLocal() as db:
        assert len(list(db.execute(select(AssistantProposal)).scalars())) == before                 # nothing drafted
        assert db.execute(select(AgentRun).order_by(AgentRun.id.desc())).scalars().first().status == 'withheld'


def test_switched_off_falls_back_to_template(coord, llm, monkeypatch):
    monkeypatch.setattr(get_settings(), 'agents_disabled', ['answer'])
    m = ask(coord, 'Which patients have overdue follow-ups?', ai=True)
    assert m['ai'] is False and 'switched off' in m['text'] and llm.calls == []


def _concurrent_write():
    """Another connection commits while the model is 'thinking' (browser session refresh, scheduler, another user)."""
    from app.models import AppSetting
    with SessionLocal() as other:
        row = other.get(AppSetting, 'concurrency-probe')
        if row is None:
            other.add(AppSetting(key='concurrency-probe', value={'n': 0}))
        else:
            row.value = {'n': (row.value or {}).get('n', 0) + 1}
        other.commit()


def test_concurrent_write_during_model_call_is_safe(coord, llm):
    """Regression: SQLite 'database is locked' when a write committed elsewhere during the provider call."""
    def slow(prompt):
        _concurrent_write()
        return good(prompt)
    llm.respond(aa.Answer, slow)
    m = ask(coord, 'Which patients need attention today?', ai=True)
    assert m['ai'] is True


def test_concurrent_write_during_recommendation_is_safe(coord, fake_llm):
    from app.services import recommendation_agent as ra
    rec = ra.Recommendation(recommendation='Contact the patient to rebook.', rationale='Missed.', task_title='Rebook')
    fake_llm.respond(ra.Recommendation, lambda prompt: (_concurrent_write(), rec)[1])
    aid = next(a['id'] for a in coord.get('/api/care-gaps').json() if a['status'] == 'Open')
    assert coord.post(f'/api/care-gaps/{aid}/recommendation').status_code in (200, 502)               # 502 only if the verifier objects
    with SessionLocal() as db:
        assert db.execute(select(AgentRun).order_by(AgentRun.id.desc())).scalars().first().agent == 'recommendation'


def test_unexpected_error_never_returns_500(coord, llm, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError('unexpected')
    monkeypatch.setattr(aa, 'ask_ai', boom)
    before = len(coord.get('/api/assistant/messages').json())
    m = ask(coord, 'Which patients have overdue follow-ups?', ai=True)
    assert m['ai'] is False and m['text'].startswith('The AI could not answer')
    assert len(coord.get('/api/assistant/messages').json()) == before + 2                          # question + answer, no duplicate


def test_no_key_falls_back_to_template(coord):
    m = ask(coord, 'Which patients have overdue follow-ups?', ai=True)
    assert m['ai'] is False and 'not configured' in m['text']
