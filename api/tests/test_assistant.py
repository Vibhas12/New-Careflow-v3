"""Phase 4: AI Care Assistant – grounded answers, scoping, proposals that need approval, conversation storage."""
import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import AuditLog, Patient, Task


def ask(c, text, pid=None):
    r = c.post('/api/assistant/messages', json={'text': text, 'patientId': pid})
    assert r.status_code == 200, r.text
    return r.json()


def test_admin_has_no_assistant(admin):
    assert admin.get('/api/assistant/messages').status_code == 403
    assert admin.post('/api/assistant/messages', json={'text': 'hello'}).status_code == 403


def test_patient_summary_is_grounded_and_cited(coord):
    m = ask(coord, 'Summarise Sarah Thompson’s patient journey')
    assert m['patientId'] == 'PT-1001' and m['role'] == 'ai'
    b = next(x for x in m['blocks'] if x['type'] == 'brief')['brief']
    assert set(b['sections']) == {'context', 'history', 'gaps', 'appointments', 'results', 'next'}
    facts = [f for s in b['sections'].values() for f in s]
    assert all(f['kind'] in ('fact', 'suggestion', 'missing') for f in facts)
    assert b['evidence'] and all(1 <= n <= len(b['evidence']) for f in facts for n in f['sources'])
    assert any('Agent' in t for t in m['trace'])


def test_doctor_cannot_ask_about_other_patients(doctor):
    with SessionLocal() as db:
        other = db.execute(select(Patient).where(Patient.doctor_id != 'u-d1')).scalars().first()
    m = ask(doctor, f'Summarise {other.first_name} {other.last_name}')
    assert m['patientId'] is None and not any(b['type'] == 'brief' for b in m['blocks'])          # outside scope → no data
    assert doctor.get(f'/api/assistant/patients/{other.id}/summary').status_code == 404


@pytest.mark.parametrize('q,expect', [('Which patients have overdue follow-ups?', 'follow-up'), ('Which diagnostic tests are awaiting review?', 'review'),
                                      ('Show patients who missed appointments this week', 'missed'), ('Which referrals are still incomplete?', 'referral'),
                                      ('Summarise the latest patient activity', 'activity'), ('Show recently imported documents', 'document'),
                                      ('How many care gaps are open?', 'care gap'), ('What is the weather?', 'won’t')])
def test_intents(coord, q, expect):
    assert expect in ask(coord, q)['text'].lower()


def test_pending_actions_scope(doctor, coord):
    assert 'Pending actions for' in ask(doctor, 'What actions are pending for me?')['text']
    assert 'own patients only' in ask(doctor, 'What actions are pending for Dr. Patel?')['text']
    assert 'Dr. Sarah Wilson' in ask(coord, 'What actions are pending for Dr. Wilson?')['text']


def test_proposals_need_approval(coord):
    m = ask(coord, 'Create a task for Michael Reed to check home BP readings')
    prop = next(b for b in m['blocks'] if b['type'] == 'proposals')['proposals'][0]
    assert prop['status'] == 'Proposed' and prop['type'] == 'task' and 'check home BP' in prop['title']
    with SessionLocal() as db:
        assert not db.execute(select(Task).where(Task.title == prop['title'])).first()                # nothing created yet
    ok = coord.post(f"/api/assistant/proposals/{prop['id']}/approve").json()
    assert ok['status'] == 'Approved' and ok['resultRef'].startswith('TSK-')
    with SessionLocal() as db:
        assert db.get(Task, ok['resultRef']).source == 'AI recommendation (approved)'
    assert coord.post(f"/api/assistant/proposals/{prop['id']}/approve").status_code == 409
    rem = next(b for b in ask(coord, 'Create a reminder for Michael Reed')['blocks'] if b['type'] == 'proposals')['proposals'][0]
    assert coord.post(f"/api/assistant/proposals/{rem['id']}/reject").json()['status'] == 'Rejected'
    assert 'which patient' in ask(coord, 'Create a task')['text'].lower()


def test_gap_actions_are_live(coord):
    m = ask(coord, 'Which patients have overdue follow-ups?')
    acts = next((b for b in m['blocks'] if b['type'] == 'gapActions'), None)
    if acts:
        aid = acts['alerts'][0]['id']
        coord.post(f'/api/care-gaps/{aid}/approve', json={})
        later = next(x for x in coord.get('/api/assistant/messages').json() if x['id'] == m['id'])
        assert all(a['id'] != aid for b in later['blocks'] if b['type'] == 'gapActions' for a in b['alerts'])   # actioned alert no longer offered


def test_history_summary_audit_and_clear(coord):
    assert coord.get('/api/assistant/prompts').json()
    s = coord.get('/api/assistant/patients/PT-1001/summary').json()
    assert s['patientName'] == 'Sarah Thompson'
    with SessionLocal() as db:
        assert db.execute(select(AuditLog).where(AuditLog.action == 'AI summary generated', AuditLog.patient_id == 'PT-1001')).first()
        assert db.execute(select(AuditLog).where(AuditLog.action == 'AI assistant query')).first()
    assert len(coord.get('/api/assistant/messages').json()) >= 2
    assert coord.delete('/api/assistant/messages').status_code == 204
    assert coord.get('/api/assistant/messages').json() == []
