"""Phase 3: care-gap detection, alert lifecycle, suggested priority and background jobs."""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Appointment, CareGapAlert, Patient, Reminder, Task

FUTURE = (date.today() + timedelta(days=15)).isoformat()


def own_patient_id(doctor):
    return doctor.get('/api/patients', params={'pageSize': 1, 'sort': 'id'}).json()['items'][0]['id']


def test_seed_scan_created_alerts_and_scope(coord, doctor, admin):
    alerts = coord.get('/api/care-gaps').json()
    assert alerts and all(a['status'] == 'Open' for a in alerts)
    pri = [a['priority'] for a in alerts]
    assert pri == sorted(pri, key=['high', 'med', 'low'].index)
    with SessionLocal() as db:
        own = set(db.execute(select(Patient.id).where(Patient.doctor_id == 'u-d1')).scalars())
    assert all(a['patientId'] in own for a in doctor.get('/api/care-gaps').json())
    assert admin.get('/api/care-gaps').status_code == 403                     # no patient-level detail for admins
    s = admin.get('/api/care-gaps/summary').json()
    assert s['totalOpen'] > 0 and len(s['categories']) == 7


def test_suggested_priority_is_advisory(coord):
    items = coord.get('/api/patients', params={'pageSize': 100}).json()['items']
    assert all(p['suggestedPriority'] in ('high', 'med', 'low') for p in items)
    p = next(x for x in items if x['suggestedPriority'] == 'high')
    if p['priority'] != 'low':
        assert coord.post(f"/api/patients/{p['id']}/priority", json={'newPriority': 'low', 'comment': 'Clinically reviewed – stable'}).status_code == 200
    coord.post('/api/care-gaps/scan')
    d = coord.get(f"/api/patients/{p['id']}").json()
    assert (d['priority'], d['suggestedPriority']) == ('low', 'high')        # rules suggest; they never overwrite the stored priority


def test_approve_creates_one_task(coord, doctor):
    a = next(x for x in coord.get('/api/care-gaps').json() if x['rule'] != 'results_review')
    r = coord.post(f"/api/care-gaps/{a['id']}/approve", json={'title': 'Call patient today', 'due': FUTURE})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['status'] == 'Actioned' and body['taskId']
    with SessionLocal() as db:
        t = db.get(Task, body['taskId'])
        assert t.title == 'Call patient today' and t.alert_id == a['id'] and t.source == 'Care-gap alert (approved)'
    assert coord.post(f"/api/care-gaps/{a['id']}/approve", json={}).status_code == 409


def test_dismiss_needs_reason(coord):
    a = coord.get('/api/care-gaps').json()[-1]
    assert coord.post(f"/api/care-gaps/{a['id']}/dismiss", json={'reason': 'no'}).status_code == 422
    r = coord.post(f"/api/care-gaps/{a['id']}/dismiss", json={'reason': 'Handled by phone with the GP practice'})
    assert r.json()['status'] == 'Dismissed' and r.json()['dismissReason'].startswith('Handled')
    assert a['id'] not in [x['id'] for x in coord.get('/api/care-gaps').json()]


def test_missed_appointment_resolves_and_reopens(coord, doctor):
    pid = own_patient_id(doctor)
    with SessionLocal() as db:
        db.add(Appointment(id='APT-CG1', patient_id=pid, doctor_id='u-d1', appt_date=date.today() - timedelta(days=2), appt_time='11:00',
                           type='Consultation', status='Scheduled'))
        db.commit()
    coord.post('/api/appointments/APT-CG1/miss')
    aid = 'ALR-missed_appt-APT-CG1'
    with SessionLocal() as db:
        assert db.get(CareGapAlert, aid).status == 'Open'                       # rescanned straight after the action
    later = coord.post('/api/appointments', json={'patientId': pid, 'doctorId': 'u-d1', 'date': FUTURE, 'time': '16:30', 'type': 'Follow-up review'}).json()
    with SessionLocal() as db:
        assert db.get(CareGapAlert, aid).status == 'Resolved'                   # a later appointment closes the gap
    coord.post(f"/api/appointments/{later['id']}/cancel", json={'reason': 'Patient travelling'})
    with SessionLocal() as db:
        assert db.get(CareGapAlert, aid).status == 'Open'                       # and cancelling it re-opens it


def test_result_review_alert_lifecycle(coord, doctor):
    pid = own_patient_id(doctor)
    t = doctor.post('/api/tests', json={'patientId': pid, 'name': 'Lipid Profile'}).json()
    coord.post(f"/api/tests/{t['id']}/schedule", json={'date': date.today().isoformat()})
    coord.post(f"/api/tests/{t['id']}/complete")
    coord.post(f"/api/tests/{t['id']}/result", json={'abnormal': True})
    a = next(x for x in doctor.get('/api/care-gaps', params={'rule': 'results_review'}).json() if x['entity'] == t['id'])
    assert a['priority'] == 'high' and a['assignee'] == 'u-d1'
    doctor.post(f"/api/tests/{t['id']}/review", json={'note': 'Statin started'})
    assert coord.get('/api/care-gaps', params={'status': 'Resolved', 'rule': 'results_review'}).json()[0]['status'] == 'Resolved'


def test_manual_scan_and_jobs(coord, admin, doctor):
    assert doctor.post('/api/care-gaps/scan').status_code == 403
    assert set(coord.post('/api/care-gaps/scan').json()) == {'opened', 'reopened', 'resolved', 'open'}
    pid = own_patient_id(doctor)
    with SessionLocal() as db:
        db.add(Reminder(id='REM-T1', kind='Appointment', ref_id='APT-X', patient_id=pid, offset_label='1d', channel='SMS',
                        scheduled_for=datetime.now(timezone.utc) - timedelta(minutes=1), status='Scheduled', message='Test reminder', simulated=True))
        db.commit()
    assert coord.post('/api/jobs/run').status_code == 403
    r = admin.post('/api/jobs/run').json()
    assert r['deliver_reminders']['ok'] and r['deliver_reminders']['result']['processed'] >= 1 and r['scan_care_gaps']['ok']
    with SessionLocal() as db:
        assert db.get(Reminder, 'REM-T1').status in ('Delivered', 'Failed') and db.get(Reminder, 'REM-T1').sent_at
    assert 'deliver_reminders' in coord.get('/api/jobs').json()
