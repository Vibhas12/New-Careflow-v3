import pytest
from sqlalchemy import text


def test_coordinator_sees_all_active_patients(coord):
    r = coord.get('/api/patients', params={'pageSize': 100})
    assert r.status_code == 200
    body = r.json()
    assert body['total'] >= 10 and len(body['items']) == body['total']
    pri = [p['priority'] for p in body['items']]
    assert pri == sorted(pri, key=['high', 'med', 'low'].index)     # default sort: priority


def test_doctor_sees_only_own_patients(doctor):
    items = doctor.get('/api/patients', params={'pageSize': 100}).json()['items']
    assert items and all(p['doctorId'] == 'u-d1' for p in items)


def test_doctor_cannot_open_another_doctors_patient(coord, doctor):
    other = next(p for p in coord.get('/api/patients', params={'pageSize': 100}).json()['items'] if p['doctorId'] != 'u-d1')
    assert doctor.get(f"/api/patients/{other['id']}").status_code == 404   # 404, so IDs cannot be probed


def test_admin_has_no_patient_access(admin):
    assert admin.get('/api/patients').status_code == 403


def test_filters_search_and_pagination(coord):
    r = coord.get('/api/patients', params={'search': 'pt-1001'}).json()
    assert [p['id'] for p in r['items']] == ['PT-1001']
    r = coord.get('/api/patients', params={'priority': 'high', 'pageSize': 100}).json()
    assert r['items'] and all(p['priority'] == 'high' for p in r['items'])
    page1 = coord.get('/api/patients', params={'pageSize': 5, 'page': 1, 'sort': 'id'}).json()
    page2 = coord.get('/api/patients', params={'pageSize': 5, 'page': 2, 'sort': 'id'}).json()
    assert len(page1['items']) == 5 and not {p['id'] for p in page1['items']} & {p['id'] for p in page2['items']}


def test_patient_detail_has_related_records_and_is_audited(coord):
    d = coord.get('/api/patients/PT-1001').json()
    assert d['firstName'] == 'Sarah' and d['doctorName'] and isinstance(d['allergies'], list)
    assert d['appointments'] and d['tests'] and d['canChangePriority'] is True
    from app.db import SessionLocal
    with SessionLocal() as db:
        n = db.execute(text("SELECT COUNT(*) FROM audit_log WHERE action='Viewed patient record' AND patient_id='PT-1001'")).scalar()
    assert n >= 1


def test_unknown_patient_404(coord):
    assert coord.get('/api/patients/PT-0000').status_code == 404


@pytest.mark.parametrize('bad', [{'pageSize': 0}, {'pageSize': 1000}, {'priority': 'urgent'}, {'sort': 'dob; drop table'}])
def test_invalid_query_rejected(coord, bad):
    assert coord.get('/api/patients', params=bad).status_code == 422
