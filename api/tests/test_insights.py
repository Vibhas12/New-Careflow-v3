"""Multi-agent phase 6: metrics pages (aggregates only), "Explain with AI" (insights agent) and the advisory "AI safety check"
(reviewer agent). Fake LLM, no network."""
import json

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import AgentRun, CareGapAlert, User
from app.services import insight_agents as ins
from app.services import recommendation_agent as ra
from app.services import summary_agent as sa


def facts(prompt: str) -> dict:
    return json.loads(prompt.split('Facts (JSON):\n', 1)[1])


def faithful(prompt: str) -> ins.Insights:
    """A well-behaved model: restates real figures, with a small-sample caveat."""
    ms = [m for m in facts(prompt)['metrics'] if m['value'] is not None][:3]
    st = [ins.InsightStatement(text=f"{m['label']} is {m['value']}{'%' if m['unit'] == '%' else ''} (n={m['n']}), a small sample to read with caution.",
                               kind='observation', metrics=[m['key']]) for m in ms]
    st.append(ins.InsightStatement(text='These are workflow measures, not clinical quality.', kind='caveat', metrics=[]))
    return ins.Insights(statements=st)


@pytest.fixture
def llm(fake_llm):
    return fake_llm.respond(ins.Insights, faithful)


# ---------------------------------------------------------------- metrics: roles and aggregates only
def test_roles(coord, doctor, admin):
    assert coord.get('/api/metrics/performance').status_code == 403
    assert doctor.get('/api/metrics/executive').status_code == 403
    assert admin.get('/api/metrics/executive').status_code == 200
    with SessionLocal() as db:
        other = db.execute(select(User).where(User.role == 'doctor', User.email != 'sarah.wilson@careflow.demo')).scalars().first().id
    d = doctor.get(f'/api/metrics/performance?doctorId={other}').json()
    assert d['doctorId'] == 'u-d1' and d['doctors'] == []                         # doctors only see their own figures
    assert admin.get(f'/api/metrics/performance?doctorId={other}').json()['doctorId'] == other


def test_payloads_are_aggregates_only(doctor, admin):
    for body in (doctor.get('/api/metrics/performance?range=all').json(), admin.get('/api/metrics/executive?range=all').json()):
        blob = json.dumps(body)
        assert 'PT-' not in blob
        assert {'key', 'label', 'value', 'display', 'unit', 'n', 'definition'} <= set(body['kpis'][0])
        assert body['weekly']['labels'] and all(len(v) == len(body['weekly']['labels']) for v in body['weekly']['series'].values())
    ex = admin.get('/api/metrics/executive?range=all').json()
    assert {d['department'] for d in ex['departments']} >= {'Cardiology', 'Neurology'} and len(ex['aiUsage']) == 3
    assert {k['key'] for k in ex['kpis']} == {'followup_completion', 'attendance', 'test_completion', 'tasks_completed', 'patients_supported',
                                               'open_care_gaps', 'missed_appointments', 'reminder_effectiveness'}


def test_bad_filters(admin):
    assert admin.get('/api/metrics/performance?dept=Astrology').status_code == 422
    assert admin.get('/api/metrics/executive?range=12').status_code == 422


# ---------------------------------------------------------------- Explain with AI
def test_get_never_calls_the_model(doctor, admin, llm):
    doctor.get('/api/metrics/performance')
    admin.get('/api/metrics/executive')
    assert llm.calls == []


def test_explain_sends_aggregates_only(doctor, admin, llm):
    r = doctor.post('/api/metrics/performance/explain', json={'range': 'all'})
    assert r.status_code == 200, r.text
    assert r.json()['model'] == 'fake-llm' and r.json()['statements']
    sent = llm.calls[0]['prompt']
    with SessionLocal() as db:
        names = [n for (n,) in db.execute(select(User.name)).all()]
    assert 'PT-' not in sent and not [n for n in names if n in sent]
    assert facts(sent)['scope'] == 'your own patients'
    r = admin.post('/api/metrics/executive/explain', json={'range': '90'})
    assert r.status_code == 200 and len(llm.calls) == 2 and facts(llm.calls[1]['prompt'])['departments']


@pytest.mark.parametrize('text, metrics, why', [
    ('Attendance is 9999%.', ['attendance'], 'number that is not in the figures'),
    ('This doctor is the best in the organisation.', [], 'ranks or judges people'),
    ('Attendance fell because reminders were not sent.', ['attendance'], 'cause'),
    ('Satisfaction scores are high.', ['patient_satisfaction'], 'not on the page'),
    ('Ask the doctor to increase the dose for these patients.', [], 'medication'),
])
def test_unsafe_explanation_is_withheld(admin, llm, text, metrics, why):
    llm.respond(ins.Insights, ins.Insights(statements=[ins.InsightStatement(text=text, kind='observation', metrics=metrics)]))
    r = admin.post('/api/metrics/executive/explain', json={'range': 'all'})
    assert r.status_code == 502 and why in r.json()['detail'], r.json()
    with SessionLocal() as db:
        run = db.execute(select(AgentRun).order_by(AgentRun.id.desc())).scalars().first()
        assert run.agent == 'insights' and run.status == 'withheld'


def test_small_sample_needs_a_caveat():
    ctx = {'rangeDays': 90, 'weekly': {'labels': [], 'series': {}}, 'departments': [],
           'metrics': [{'key': 'attendance', 'label': 'Appointment attendance', 'value': 50, 'unit': '%', 'n': 2, 'definition': '…'},
                       {'key': 'tasks_completed', 'label': 'Tasks completed', 'value': 40, 'unit': 'count', 'n': 40, 'definition': '…'}]}
    agent = ins.InsightsAgent()
    say = lambda text, keys: agent.verify(ins.Insights(statements=[ins.InsightStatement(text=text, kind='observation', metrics=keys)]), ctx)
    assert any('small sample (attendance n=2)' in i for i in say('Attendance is 50%.', ['attendance']))
    assert say('Attendance is 50%, but only 2 appointments – a small sample.', ['attendance']) == []
    assert say('40 tasks were completed.', ['tasks_completed']) == []                       # n=40: no caveat needed
    ctx['metrics'].append({'key': 'open_care_gaps', 'label': 'Outstanding care gaps', 'value': 0, 'unit': 'count', 'n': 0, 'definition': '…'})
    assert say('There are 0 outstanding care gaps.', ['open_care_gaps']) == []              # seen live: a count of 0 is a fact, not a sample
    assert any('not in the figures (41)' in i for i in say('41 tasks were completed.', ['tasks_completed']))


# ---------------------------------------------------------------- AI safety check (advisory)
def test_safety_check_on_care_gap_wording(coord, fake_llm):
    fake_llm.respond(ra.Recommendation, ra.Recommendation(recommendation='Contact the patient today to rebook the appointment.',
                                                          rationale='The appointment was missed.', task_title='Contact patient to rebook'))
    aid = next(a['id'] for a in coord.get('/api/care-gaps').json() if a['status'] == 'Open')
    with SessionLocal() as db:
        a = db.get(CareGapAlert, aid)
        a.ai_text = a.ai_source_hash = a.ai_error = None
        db.commit()
    assert coord.post(f'/api/care-gaps/{aid}/safety-check').status_code == 409         # nothing to check yet
    assert coord.post(f'/api/care-gaps/{aid}/recommendation').status_code == 200
    fake_llm.respond(ins.Review, ins.Review(verdict='concerns', concerns=[ins.Concern(issue='"today" may overstate the urgency.', severity='low',
                                                                                        quote='Contact the patient today')]))
    r = coord.post(f'/api/care-gaps/{aid}/safety-check')
    assert r.status_code == 200, r.text
    assert r.json()['verdict'] == 'concerns' and r.json()['concerns'][0]['severity'] == 'low'
    a = next(x for x in coord.get('/api/care-gaps').json() if x['id'] == aid)
    assert a['aiStatus'] == 'ready' and a['aiText'].startswith('Contact the patient today')    # advisory: nothing changed
    ctx = facts(fake_llm.calls[-1]['prompt'])
    assert ctx['ai_output']['recommendation'].startswith('Contact the patient') and 'care_gap_category' in ctx['facts']


def test_reviewer_quote_must_be_real(coord, fake_llm):
    fake_llm.respond(ra.Recommendation, ra.Recommendation(recommendation='Call the patient to book the review.', rationale='Overdue.', task_title='Book review'))
    aid = next(a['id'] for a in coord.get('/api/care-gaps').json() if a['status'] == 'Open')
    coord.post(f'/api/care-gaps/{aid}/recommendation')
    fake_llm.respond(ins.Review, ins.Review(verdict='concerns', concerns=[ins.Concern(issue='Invented quote.', severity='high', quote='prescribe insulin now')]))
    r = coord.post(f'/api/care-gaps/{aid}/safety-check')
    assert r.status_code == 502 and 'not in the AI output' in r.json()['detail']


def test_safety_check_on_ai_summary(coord, doctor, fake_llm):
    pid = next(a['patientId'] for a in coord.get('/api/care-gaps').json() if a['status'] == 'Open')

    def faithful_summary(prompt):
        ctx = facts(prompt)
        parts = {s: [sa.Statement(text=f['text'], kind=f['kind'], sources=f['sources']) for f in ctx['facts'] if f['section'] == s] for s in sa.SECTIONS}
        return sa.PatientSummary(overview=(parts['gaps'] or parts['context'])[:1], **parts)
    fake_llm.respond(sa.PatientSummary, faithful_summary)
    assert coord.post(f'/api/assistant/patients/{pid}/summary/ai').status_code == 200
    fake_llm.respond(ins.Review, ins.Review(verdict='no concerns', concerns=[]))
    r = coord.post(f'/api/assistant/patients/{pid}/summary/safety-check')
    assert r.status_code == 200 and r.json()['verdict'] == 'no concerns'
    with SessionLocal() as db:
        me = db.execute(select(User).where(User.email == 'sarah.wilson@careflow.demo')).scalars().one()
        from app.models import Patient
        other = db.execute(select(Patient).where(Patient.doctor_id != me.id)).scalars().first().id
    assert doctor.post(f'/api/assistant/patients/{other}/summary/safety-check').status_code == 404      # scoped like everything else
