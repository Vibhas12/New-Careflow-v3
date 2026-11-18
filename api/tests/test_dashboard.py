"""Endpoints that back the V2 look-and-feel: dashboards, derived patient facts, appointment detail, calls and manual reminders."""
from sqlalchemy import select

from app.db import SessionLocal
from app.models import AuditLog, Reminder


def test_dashboards_per_role(coord, doctor, admin):
    c = coord.get('/api/dashboard').json()
    assert set(c['kpis']) == {'assigned', 'high', 'upcoming7', 'pendingTests', 'openTasks'} and c['patients']
    assert all('attention' in p and 'lastVisit' in p for p in c['patients'])
    d = doctor.get('/api/dashboard').json()
    assert set(d['review']) == {'results', 'abnormal', 'overdue', 'plan', 'referrals'} and all(p['doctorId'] == 'u-d1' for p in d['patients'])
    a = admin.get('/api/dashboard').json()
    assert len(a['next7']) == 7 and len(a['gapsByCategory']) == 7 and a['team'] and 'patients' not in a    # no patient-level data for admins


def test_patient_derived_fields_filters_and_sort(coord):
    items = coord.get('/api/patients', params={'pageSize': 100}).json()['items']
    assert {'status', 'lastVisit', 'nextAppt', 'followUpStatus', 'mobile'} <= set(items[0])
    st = items[0]['status']
    assert all(p['status'] == st for p in coord.get('/api/patients', params={'status': st, 'pageSize': 100}).json()['items'])
    cond = items[0]['primaryCondition'].split()[0].lower()
    assert coord.get('/api/patients', params={'search': cond}).json()['total'] >= 1             # search includes the condition
    by_appt = coord.get('/api/patients', params={'sort': 'nextAppt', 'pageSize': 100}).json()['items']
    dates = [p['nextAppt']['date'] for p in by_appt if p['nextAppt']]
    assert dates == sorted(dates)
    d = coord.get(f"/api/patients/{items[0]['id']}").json()
    assert {'careGaps', 'activity', 'documents', 'status'} <= set(d)


def test_appointment_detail_call_and_reminder(coord, doctor, admin):
    a = coord.get('/api/appointments').json()['items'][0]
    r = coord.get(f"/api/appointments/{a['id']}").json()
    assert r['id'] == a['id'] and isinstance(r['reminders'], list)
    assert admin.get(f"/api/appointments/{a['id']}").json()['reminders'] == []                  # reminder detail hidden from admins
    pid = a['patientId']
    assert coord.post(f'/api/patients/{pid}/calls', json={'outcome': 'No answer', 'notes': 'Try again tomorrow'}).status_code == 204
    assert coord.post(f'/api/patients/{pid}/calls', json={'outcome': 'Shouted'}).status_code == 422
    res = coord.post(f'/api/patients/{pid}/reminders', json={'type': 'Follow-up request', 'channel': 'SMS', 'message': 'Please call us to book.'})
    assert res.status_code == 201 and res.json()['status'] in ('Delivered', 'Failed')
    with SessionLocal() as db:
        assert db.get(Reminder, res.json()['id']).simulated
        assert db.execute(select(AuditLog).where(AuditLog.action == 'Patient call logged', AuditLog.detail == 'Phone call: No answer – Try again tomorrow')).first()
    assert admin.post(f'/api/patients/{pid}/reminders', json={'type': 'Follow-up request', 'channel': 'SMS', 'message': 'Hello there'}).status_code == 403
