import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError


def _current(client, pid):
    return client.get(f'/api/patients/{pid}').json()['priority']


def test_coordinator_changes_priority_with_history(coord):
    pid = 'PT-1002'
    old = _current(coord, pid)
    new = 'low' if old != 'low' else 'high'
    r = coord.post(f'/api/patients/{pid}/priority', json={'newPriority': new, 'comment': 'Reviewed at MDT – stable'})
    assert r.status_code == 200, r.text
    e = r.json()
    assert (e['previousPriority'], e['newPriority'], e['userRole']) == (old, new, 'coordinator')
    assert _current(coord, pid) == new
    hist = coord.get(f'/api/patients/{pid}/priority-history').json()
    assert hist[0]['previousPriority'] is None and hist[-1]['id'] == e['id']


def test_comment_is_mandatory(coord):
    assert coord.post('/api/patients/PT-1003/priority', json={'newPriority': 'high', 'comment': '  '}).status_code == 422


def test_same_priority_rejected(coord):
    cur = _current(coord, 'PT-1004')
    assert coord.post('/api/patients/PT-1004/priority', json={'newPriority': cur, 'comment': 'No change really'}).status_code == 409


def test_doctor_own_patient_only(doctor, coord):
    own = doctor.get('/api/patients', params={'pageSize': 1}).json()['items'][0]
    new = 'low' if own['priority'] != 'low' else 'med'
    assert doctor.post(f"/api/patients/{own['id']}/priority", json={'newPriority': new, 'comment': 'Doctor review today'}).status_code == 200
    other = next(p for p in coord.get('/api/patients', params={'pageSize': 100}).json()['items'] if p['doctorId'] != 'u-d1')
    assert doctor.post(f"/api/patients/{other['id']}/priority", json={'newPriority': 'high', 'comment': 'Not my patient'}).status_code == 404


def test_admin_cannot_change_priority(admin):
    assert admin.post('/api/patients/PT-1001/priority', json={'newPriority': 'low', 'comment': 'Admin attempt'}).status_code == 403


@pytest.mark.parametrize('sql', ["UPDATE priority_history SET comment='tampered'", 'DELETE FROM priority_history'])
def test_history_is_immutable_in_the_database(sql):
    from app.db import SessionLocal
    with SessionLocal() as db, pytest.raises(DatabaseError, match='immutable'):
        db.execute(text(sql))
