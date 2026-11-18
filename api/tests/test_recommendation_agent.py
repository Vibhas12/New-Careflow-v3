"""Gemini recommendation agent – tested with a fake LLM (no network): de-identification, storage, staleness, fallback, approval."""
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db import SessionLocal
from app.models import CareGapAlert, Patient, Task
from app.services import recommendation_agent as agent


@pytest.fixture
def llm_on(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, 'llm_enabled', True)
    monkeypatch.setattr(s, 'gemini_api_key', 'test-key')
    sent = []

    def fake(context):
        sent.append(context)
        return agent.Recommendation(recommendation='Call the patient today and offer the next available review slot.',
                                    rationale='The review date has passed with nothing booked.', task_title='Call patient to book overdue review'), 'gemini-test'
    monkeypatch.setattr(agent, 'call_llm', fake)
    return sent


def first_open(db, rule=None):
    q = select(CareGapAlert).where(CareGapAlert.status == 'Open')
    if rule:
        q = q.where(CareGapAlert.rule == rule)
    return db.execute(q).scalars().first()


def test_context_is_deidentified():
    with SessionLocal() as db:
        a = first_open(db)
        p = db.get(Patient, a.patient_id)
        a.reason = f'Task "Schedule HbA1c for {p.full_name}" ({p.id}) is overdue.'
        ctx = agent.build_context(a, p)
        first, last, pid, dept, cond, mobile = p.first_name, p.last_name, p.id, p.department, p.primary_condition, p.mobile
        db.rollback()
    blob = str(ctx)
    assert first not in blob and last not in blob and pid not in blob
    assert ctx['patient_context'] == {'department': dept, 'primary_condition': cond}
    assert 'dob' not in blob.lower() and (mobile or '§') not in blob


def test_off_without_key(coord):
    alerts = coord.get('/api/care-gaps').json()
    assert alerts and all(a['aiStatus'] == 'off' and a['aiText'] is None for a in alerts)
    assert coord.post(f"/api/care-gaps/{alerts[0]['id']}/recommendation").status_code == 503


def test_word_store_and_show(coord, llm_on):
    aid = coord.get('/api/care-gaps').json()[0]['id']
    assert coord.get('/api/care-gaps').json()[0]['aiStatus'] in ('pending', 'error')
    r = coord.post(f'/api/care-gaps/{aid}/recommendation')
    assert r.status_code == 200, r.text
    a = r.json()
    assert a['aiStatus'] == 'ready' and a['aiModel'] == 'gemini-test' and a['aiText'].startswith('Call the patient')
    assert len(llm_on) == 1


def test_stale_wording_is_hidden_after_facts_change(coord, llm_on):
    aid = coord.get('/api/care-gaps').json()[0]['id']
    coord.post(f'/api/care-gaps/{aid}/recommendation')
    with SessionLocal() as db:
        a = db.get(CareGapAlert, aid)
        a.reason = a.reason + ' (updated by a rescan)'
        db.commit()
    a = next(x for x in coord.get('/api/care-gaps').json() if x['id'] == aid)
    assert a['aiStatus'] == 'pending' and a['aiText'] is None              # never show wording for facts that changed


def test_failure_falls_back_to_template(coord, llm_on, monkeypatch):
    def boom(context):
        raise agent.LLMUnavailable('Gemini API error 429: quota')
    monkeypatch.setattr(agent, 'call_llm', boom)
    with SessionLocal() as db:
        a = first_open(db)
        a.ai_text = None; a.ai_source_hash = None
        db.commit()
        aid = a.id
    assert coord.post(f'/api/care-gaps/{aid}/recommendation').status_code == 502
    a = next(x for x in coord.get('/api/care-gaps').json() if x['id'] == aid)
    assert a['aiStatus'] == 'error' and 'quota' in a['aiError'] and a['action']['text']      # rule template still there


def test_background_job_words_pending(llm_on):
    from app.jobs import word_recommendations
    with SessionLocal() as db:
        r = word_recommendations(db)
        assert r['worded'] >= 1 and r['failed'] == 0
        assert all(agent.is_current(a) for a in db.execute(select(CareGapAlert).where(CareGapAlert.status == 'Open')).scalars()
                   ) or r['remaining'] > 0


def test_approve_uses_ai_wording(coord, llm_on):
    alerts = [a for a in coord.get('/api/care-gaps').json() if a['status'] == 'Open']
    aid = alerts[-1]['id']
    coord.post(f'/api/care-gaps/{aid}/recommendation')
    task_id = coord.post(f'/api/care-gaps/{aid}/approve', json={}).json()['taskId']
    with SessionLocal() as db:
        t = db.get(Task, task_id)
        assert t.title.startswith('Call patient to book overdue review') and 'Wording by gemini-test' in t.description
