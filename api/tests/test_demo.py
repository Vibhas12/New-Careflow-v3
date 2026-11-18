"""Sign-in demo scenarios: no patient data by default, chosen scenario replaces everything, safeguards stay in place."""
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DatabaseError

from app.db import SessionLocal
from app.models import AuditLog, Patient, PriorityHistory, User


def count(model):
    with SessionLocal() as db:
        return db.execute(select(func.count()).select_from(model)).scalar_one()


def test_reference_seed_has_no_patients():
    from app.seed import seed_reference
    with SessionLocal() as db:
        assert seed_reference(db) is False            # accounts already exist → nothing to do, and never adds patients


def test_scenarios_listed_before_sign_in(anon):
    r = anon.get('/api/demo/scenarios').json()
    assert r['enabled'] and r['hasData'] is True
    assert [s['id'] for s in r['scenarios']] == ['empty', 'baseline', 'escalation', 'recovery', 'full', 'v2']


def test_load_requires_sign_in(anon):
    assert anon.post('/api/demo/load', json={'scenario': 'empty'}).status_code == 401


def test_scenarios_replace_data(doctor, coord):
    users_before = count(User)
    r = doctor.post('/api/demo/load', json={'scenario': 'empty'})
    assert r.status_code == 200 and r.json()['patients'] == 0
    assert count(Patient) == 0 and count(PriorityHistory) == 0 and count(User) == users_before
    assert doctor.get('/api/auth/me').status_code == 200                        # sessions survive the reset

    r = doctor.post('/api/demo/load', json={'scenario': 'escalation'}).json()
    assert r['patients'] == 10 and [i['failed'] for i in r['imports']] == [0, 0]
    pts = {p['id']: p for p in coord.get('/api/patients', params={'pageSize': 100}).json()['items']}
    assert set(pts) == {f'PT-30{n:02d}' for n in range(1, 11)}                 # only what was chosen – no V2 patients
    assert pts['PT-3003']['priority'] == 'high' and pts['PT-3005']['coordId']  # escalation applied; coordinator assigned
    assert coord.get('/api/care-gaps').json()                                   # alerts detected for the loaded data

    r = coord.post('/api/demo/load', json={'scenario': 'full'}).json()
    assert r['patients'] == 11 and r['imports'][-1]['failed'] == 4             # data-quality rows rejected as designed
    assert coord.post('/api/demo/load', json={'scenario': 'nope'}).status_code == 422


def test_history_still_immutable_after_reset():
    with SessionLocal() as db, pytest.raises(DatabaseError, match='immutable'):
        db.execute(text('DELETE FROM priority_history'))


def test_disabled_in_production(monkeypatch, coord):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), 'env', 'production')
    assert coord.get('/api/demo/scenarios').json() == {'enabled': False, 'scenarios': [], 'hasData': None}
    assert coord.post('/api/demo/load', json={'scenario': 'empty'}).status_code == 404


def test_restore_v2_for_remaining_tests(coord):
    r = coord.post('/api/demo/load', json={'scenario': 'v2'}).json()
    assert r['patients'] == 15
    with SessionLocal() as db:
        assert db.execute(select(AuditLog).where(AuditLog.action == 'Demo scenario loaded')).first()
